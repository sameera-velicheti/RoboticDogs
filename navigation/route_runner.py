"""Runs a route: drive to each waypoint, do its action, report progress.

Recovery rules (from the brainstorming doc):
- A waypoint that can't be reached is retried up to its "retries" count.
- An optional waypoint ("required": false) is skipped if it still fails.
- A required waypoint that still fails ends the route.

Every step sends a status event (a dict) to on_event, so the UI can show
progress. Event shape:
    {"dog": "Pumbaa", "status": "navigating", "waypoint": 2, "total": 5,
     "waypoint_name": "Checkpoint2", "message": "...", "image": None}

Try it with no robot:
    python -m navigation.route_runner routes/ops_center.json --mock
    python -m navigation.route_runner routes/ops_center.json --mock --fail-rate 0.3
"""

import argparse
import json
import time

from navigation.route_loader import load_route
from navigation.navigator import MockNavigator


class RouteRunner:

    def __init__(self, navigator, dog_name="Pumbaa", capture=None, on_event=None):
        """
        navigator: MockNavigator or RosNavigator
        capture:   function that takes a picture and returns its file path
                   (for a real dog: bridge.take_picture)
        on_event:  function that receives each status event dict
        """
        self.navigator = navigator
        self.dog_name = dog_name
        self.capture = capture or (lambda: None)
        self.on_event = on_event or (lambda e: print(json.dumps(e)))
        self._stop_requested = False

    def stop(self):
        """Emergency stop: cancel the current goal and end the route."""
        self._stop_requested = True
        self.navigator.cancel()

    def _emit(self, status, index, total, wp=None, message="", image=None):
        self.on_event({
            "dog": self.dog_name,
            "status": status,
            "waypoint": index,
            "total": total,
            "waypoint_name": wp["name"] if wp else None,
            "message": message,
            "image": image,
            "time": time.strftime("%H:%M:%S"),
        })

    def run(self, route):
        """Run every waypoint. Returns a summary dict."""
        waypoints = route["waypoints"]
        total = len(waypoints)
        summary = {"route": route["route_name"], "dog": self.dog_name,
                   "reached": [], "skipped": [], "images": [], "completed": False}

        self._emit("route_started", 0, total, message=route["route_name"])

        for i, wp in enumerate(waypoints, start=1):
            if self._stop_requested:
                self._emit("route_stopped", i, total, wp, "Stopped by user")
                return summary

            result = None
            for attempt in range(1, wp["retries"] + 2):
                self._emit("navigating", i, total, wp, f"Attempt {attempt}")
                result = self.navigator.go_to(wp["x"], wp["y"], wp["yaw"])
                if result.success or self._stop_requested:
                    break
                self._emit("retrying", i, total, wp, result.message)

            if self._stop_requested:
                self._emit("route_stopped", i, total, wp, "Stopped by user")
                return summary

            if not result.success:
                if wp["required"]:
                    self._emit("route_failed", i, total, wp,
                               f"Required waypoint unreachable: {result.message}")
                    return summary
                self._emit("skipped", i, total, wp, result.message)
                summary["skipped"].append(wp["name"])
                continue

            self._emit("arrived", i, total, wp)
            summary["reached"].append(wp["name"])

            if wp["action"] == "capture_image":
                try:
                    image = self.capture()
                    summary["images"].append(image)
                    self._emit("captured", i, total, wp, image=image)
                except Exception as e:  # a bad photo should not end the route
                    self._emit("capture_failed", i, total, wp, str(e))

        summary["completed"] = True
        self._emit("route_completed", total, total, message=route["route_name"])
        return summary


def main():
    parser = argparse.ArgumentParser(description="Run a waypoint route")
    parser.add_argument("route_file")
    parser.add_argument("--mock", action="store_true", help="no robot, fake navigation")
    parser.add_argument("--fail-rate", type=float, default=0.0)
    parser.add_argument("--dog", default="Pumbaa")
    parser.add_argument("--ip", help="dog IP for a real run, e.g. 192.168.0.60")
    args = parser.parse_args()

    route = load_route(args.route_file)

    if args.mock:
        navigator = MockNavigator(travel_time=0.5, fail_rate=args.fail_rate)
        capture = lambda: f"captures/mock_{args.dog}_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
        RouteRunner(navigator, args.dog, capture).run(route)
        return

    if not args.ip:
        parser.error("--ip is required unless --mock is used")

    from ros2_bridge.ros_nodes import RosPugBridge
    from navigation.navigator import RosNavigator

    bridge = RosPugBridge(args.ip, robot_name=args.dog)
    navigator = RosNavigator(bridge.client)
    runner = RouteRunner(navigator, args.dog, capture=bridge.take_picture)
    try:
        runner.run(route)
    except KeyboardInterrupt:
        runner.stop()
    finally:
        navigator.close()
        bridge.close()


if __name__ == "__main__":
    main()