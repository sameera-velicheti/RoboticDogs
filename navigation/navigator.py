"""Navigators move a dog to a point on the map.

Every navigator has the same method, go_to(x, y, yaw), so the route runner
does not care whether it is talking to a real dog or a fake one.

- MockNavigator: no robot needed. Use it on remote days and in tests.
- RosNavigator:  sends goals to move_base on the dog over rosbridge (roslibpy),
                 the same connection RosPugBridge already uses.
"""

import math
import random
import threading
import time
import uuid
from dataclasses import dataclass


@dataclass
class NavResult:
    success: bool
    message: str = ""


class Navigator:
    """Base class. Subclasses implement go_to and cancel."""

    def go_to(self, x, y, yaw, timeout=60.0) -> NavResult:
        raise NotImplementedError

    def cancel(self):
        pass


class MockNavigator(Navigator):
    """Pretends to drive. Fails at random (fail_rate) or at named spots.

    fail_at: set of (x, y) tuples that always fail, for testing recovery.
    """

    def __init__(self, travel_time=1.0, fail_rate=0.0, fail_at=None, seed=None):
        self.travel_time = travel_time
        self.fail_rate = fail_rate
        self.fail_at = set(fail_at or [])
        self.rng = random.Random(seed)
        self.position = (0.0, 0.0, 0.0)

    def go_to(self, x, y, yaw, timeout=60.0):
        time.sleep(self.travel_time)
        if (x, y) in self.fail_at or self.rng.random() < self.fail_rate:
            return NavResult(False, f"Mock: could not reach ({x}, {y})")
        self.position = (x, y, yaw)
        return NavResult(True, "Mock: arrived")


def yaw_to_quaternion(yaw):
    """Convert a heading in radians to a ROS quaternion dict."""
    return {"x": 0.0, "y": 0.0, "z": math.sin(yaw / 2.0), "w": math.cos(yaw / 2.0)}


def quaternion_to_yaw(q):
    """Convert a ROS quaternion dict to a heading in radians."""
    siny = 2.0 * (q["w"] * q["z"] + q["x"] * q["y"])
    cosy = 1.0 - 2.0 * (q["y"] ** 2 + q["z"] ** 2)
    return math.atan2(siny, cosy)


# actionlib status codes
_SUCCEEDED = 3
_STATUS_TEXT = {
    2: "preempted", 3: "succeeded", 4: "aborted (no path / stuck)",
    5: "rejected", 8: "recalled",
}


class RosNavigator(Navigator):
    """Sends a goal to move_base and waits for the result.

    Needs on the dog: map_server + amcl (localization) and move_base running,
    plus rosbridge on port 9090 (already used by the app).

    Topic names are the move_base defaults. Confirm them on Thursday with
    `rostopic list | grep move_base` and change action_ns if needed.
    """

    def __init__(self, ros_client, action_ns="/move_base", frame_id="map"):
        import roslibpy  # imported here so tests run without roslibpy

        self._roslibpy = roslibpy
        self.client = ros_client
        self.frame_id = frame_id
        self._goal_id = None
        self._result = None
        self._done = threading.Event()

        self._goal_pub = roslibpy.Topic(
            ros_client, f"{action_ns}/goal", "move_base_msgs/MoveBaseActionGoal")
        self._cancel_pub = roslibpy.Topic(
            ros_client, f"{action_ns}/cancel", "actionlib_msgs/GoalID")
        self._result_sub = roslibpy.Topic(
            ros_client, f"{action_ns}/result", "move_base_msgs/MoveBaseActionResult")
        self._result_sub.subscribe(self._on_result)

    def _on_result(self, msg):
        status = msg.get("status", {})
        if status.get("goal_id", {}).get("id") == self._goal_id:
            self._result = status.get("status")
            self._done.set()

    def go_to(self, x, y, yaw, timeout=60.0):
        self._goal_id = f"robodog_{uuid.uuid4().hex[:8]}"
        self._result = None
        self._done.clear()

        zero = {"secs": 0, "nsecs": 0}
        self._goal_pub.publish(self._roslibpy.Message({
            "header": {"frame_id": self.frame_id, "stamp": zero},
            "goal_id": {"id": self._goal_id, "stamp": zero},
            "goal": {"target_pose": {
                "header": {"frame_id": self.frame_id, "stamp": zero},
                "pose": {
                    "position": {"x": float(x), "y": float(y), "z": 0.0},
                    "orientation": yaw_to_quaternion(float(yaw)),
                },
            }},
        }))

        if not self._done.wait(timeout):
            self.cancel()
            return NavResult(False, f"Timed out after {timeout:.0f}s")

        if self._result == _SUCCEEDED:
            return NavResult(True, "Arrived")
        return NavResult(False, f"move_base {_STATUS_TEXT.get(self._result, self._result)}")

    def cancel(self):
        if self._goal_id:
            self._cancel_pub.publish(self._roslibpy.Message(
                {"id": self._goal_id, "stamp": {"secs": 0, "nsecs": 0}}))

    def close(self):
        self._result_sub.unsubscribe()