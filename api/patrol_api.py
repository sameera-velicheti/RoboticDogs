"""
Patrol API for Agentic Paw Patrol.

Handles:
- Starting saved waypoint inspection routes
- Stopping waypoint routes
- Emergency cancellation
- Legacy Phase 1 command requests

Actual waypoint navigation remains in:
    navigation/navigator.py
    navigation/route_runner.py
    navigation/route_loader.py
"""

import json
import os
import queue
import threading
from datetime import datetime

from flask import Blueprint, Response, request, stream_with_context

from navigation.navigator import RosNavigator
from navigation.route_loader import load_route
from navigation.route_runner import RouteRunner
from navigation import traffic

from runtime import (
    CAPTURE_DIR,
    DOG_NAMES,
    PATROL_END,
    ROUTES_DIR,
    emergency_stop_robot,
    get_bridge,
    get_cancel_event,
    is_patrolling,
    register_patrol,
    remove_patrol,
    safe_name,
    stop_patrol,
)

from services.legacy_commands import stream_command


patrol_bp = Blueprint("patrol", __name__)


# ---------------------------------------------------------------------------
# Start waypoint patrol
# ---------------------------------------------------------------------------

@patrol_bp.route("/patrol/start", methods=["POST"])
def patrol_start():
    """
    Start a saved waypoint route for one dog.

    RouteRunner handles waypoint sequencing and recovery.
    RosNavigator handles the actual move_base navigation goals.
    """

    data = request.get_json(silent=True) or {}

    dog_id = data.get("dog_id", "dog1")
    route_file = os.path.basename(
        data.get("route", "data_center.json")
    )
    dog_name = DOG_NAMES.get(dog_id, dog_id)

    if is_patrolling(dog_id):
        return {
            "error": f"{dog_name} is already on patrol"
        }, 409

    try:
        route = load_route(
            os.path.join(ROUTES_DIR, route_file)
        )
    except Exception as error:
        return {
            "error": f"Could not load route {route_file}: {error}"
        }, 400

    # Resume: start at a later stop and keep the dog's current position
    # (don't reset it to the taped start spot).
    resume = bool(data.get("resume"))
    total_stops = len(route["waypoints"])

    try:
        start_at = int(data.get("start_at", 1))
    except (TypeError, ValueError):
        start_at = 0

    if not 1 <= start_at <= total_stops:
        return {
            "error": f"Stop number must be between 1 and {total_stops}"
        }, 400

    events = queue.Queue()

    def generate():

        def sse(kind, payload):
            return (
                f"data: "
                f"{json.dumps({'type': kind, **payload})}"
                f"\n\n"
            )

        yield sse(
            "log",
            {
                "msg": f"Connecting to {dog_name}..."
            }
        )

        # Connect to the dog's ROS navigation stack.
        try:
            bridge = get_bridge(dog_id)
            navigator = RosNavigator(bridge.client)

        except Exception as error:
            yield sse(
                "error",
                {
                    "msg":
                        f"{error}. "
                        "Is patrol.launch running on the dog?"
                }
            )
            return

        # Capture an image at a named waypoint.
        def capture(waypoint_name):

            try:
                path = bridge.take_picture(
                    save_dir=CAPTURE_DIR
                )
            except Exception as error:
                raise RuntimeError(
                    f"{dog_name}'s camera isn't sending images. "
                    "Reboot the dog, then Pair & Connect again."
                ) from error

            stamp = datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )

            new_path = os.path.join(
                CAPTURE_DIR,
                (
                    f"{dog_name}_"
                    f"{safe_name(waypoint_name)}_"
                    f"{stamp}.jpg"
                )
            )

            os.replace(
                path,
                new_path
            )

            return new_path

        # Keep right to pass other dogs in the aisle (navigation/traffic.py).
        try:
            traffic.track(dog_id, bridge.client)
        except Exception:
            pass

        runner = RouteRunner(
            navigator,
            dog_name,
            capture=capture,
            on_event=events.put,
            adjust_goal=lambda x, y, yaw: traffic.adjust_goal(
                dog_id, x, y, yaw, names=DOG_NAMES
            )
        )

        register_patrol(
            dog_id,
            runner
        )

        # RouteRunner blocks while executing a route, so run it in a
        # background thread while this request streams updates to the UI.
        def run():

            try:
                runner.run(
                    route,
                    start_at=start_at,
                    localize=not resume
                )

            except Exception as error:
                events.put({
                    "status": "route_failed",
                    "message": str(error),
                    "waypoint": 0,
                    "total": 0,
                    "waypoint_name": None
                })

            finally:

                try:
                    navigator.close()
                except Exception:
                    pass

                remove_patrol(dog_id)
                traffic.forget(dog_id)

                # End the server-sent event stream.
                events.put(None)

        threading.Thread(
            target=run,
            daemon=True
        ).start()

        # Tell the UI what waypoints are included in this route.
        steps = [
            waypoint["name"]
            for waypoint in route["waypoints"]
        ]

        yield sse(
            "plan",
            {
                "actions": steps,
                "total": len(steps),
                "start_at": start_at,
                "resume": resume
            }
        )

        # Stream RouteRunner events to the frontend.
        while True:

            try:
                event = events.get(
                    timeout=15
                )

            except queue.Empty:
                yield ": keep-alive\n\n"
                continue

            if event is None:
                break

            route_status = event.get("status")

            where = (
                f"[{event.get('waypoint')}/{event.get('total')}] "
                f"{event.get('waypoint_name') or ''}"
            ).strip()

            message = (
                f"{where} "
                f"{route_status.replace('_', ' ')}"
            )

            if event.get("message"):
                message += f": {event['message']}"

            yield sse(
                "log",
                {
                    "msg": message
                }
            )

            index = (
                (event.get("waypoint") or 1)
                - 1
            )

            if route_status == "navigating":

                yield sse(
                    "action_start",
                    {
                        "index": index,
                        "action": event["waypoint_name"],
                        "total": event.get("total")
                    }
                )

            elif route_status in (
                "arrived",
                "skipped"
            ):

                yield sse(
                    "action_done",
                    {
                        "index": index,
                        "action": event["waypoint_name"]
                    }
                )

            elif route_status == "capture_failed":

                yield sse(
                    "warning",
                    {
                        "msg":
                            f"No photo at "
                            f"{event.get('waypoint_name') or 'this stop'}: "
                            f"{event.get('message') or 'camera error'}"
                    }
                )

            elif (
                route_status == "captured"
                and event.get("image")
            ):

                label = os.path.basename(
                    event["image"]
                )

                yield sse(
                    "image",
                    {
                        "src": f"/captures/{label}",
                        "filepath": event["image"],     
                        "label": label,
                        "captured_at": event.get(
                            "time",
                            ""
                        ),
                        "dog_id": dog_id,
                        "waypoint_name": event.get(
                            "waypoint_name"
                        ),
                        "route_name": route["route_name"]
                    }
                )

            elif route_status in PATROL_END:

                yield sse(
                    PATROL_END[route_status],
                    {
                        "msg":
                            f"{route['route_name']}: "
                            f"{route_status.replace('_', ' ')}"
                    }
                )

    return Response(
        stream_with_context(
            generate()
        ),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


# ---------------------------------------------------------------------------
# Stop waypoint patrol
# ---------------------------------------------------------------------------

@patrol_bp.route("/patrol/stop", methods=["POST"])
def patrol_stop():
    """
    Stop the selected dog's active waypoint patrol and halt the robot.
    """

    data = request.get_json(silent=True) or {}

    dog_id = data.get(
        "dog_id",
        "dog1"
    )

    was_running = stop_patrol(
        dog_id
    )

    try:
        emergency_stop_robot(
            get_bridge(dog_id)
        )
    except Exception:
        pass

    return {
        "status":
            "stopped"
            if was_running
            else "not_running"
    }


# ---------------------------------------------------------------------------
# Emergency cancel
# ---------------------------------------------------------------------------

@patrol_bp.route("/cancel", methods=["POST"])
def cancel():
    """
    Cancel an active waypoint patrol or Phase 1 movement command.

    Navigation is cancelled first, then the robot is stopped.
    """

    data = request.get_json(silent=True) or {}

    dog_id = data.get(
        "dog_id",
        "dog1"
    )

    # Cancel the waypoint navigation goal first.
    stop_patrol(dog_id)

    # Then halt the dog.
    try:
        bridge = get_bridge(dog_id)
        emergency_stop_robot(bridge)
    except Exception:
        pass

    # Notify the old Phase 1 movement loop too.
    get_cancel_event(dog_id).set()

    return {
        "status": "cancelled"
    }


# ---------------------------------------------------------------------------
# Legacy Phase 1 movement command
# ---------------------------------------------------------------------------

@patrol_bp.route("/command", methods=["POST"])
def command():
    """
    Execute a Phase 1 natural-language robot movement command.

    The actual command-processing implementation lives in:
        services/legacy_commands.py
    """

    data = request.get_json(silent=True) or {}

    user_input = data.get(
        "input",
        ""
    ).strip()

    dog_id = data.get(
        "dog_id",
        "dog1"
    )

    if not user_input:
        return {
            "error": "Empty input"
        }, 400

    return Response(
        stream_with_context(
            stream_command(
                user_input,
                dog_id
            )
        ),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )