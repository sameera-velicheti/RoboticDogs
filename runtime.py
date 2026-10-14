"""
Shared runtime state for Agentic Paw Patrol.

This module contains application-wide resources that need to be shared
between multiple Flask API modules.

Shared resources include:
- Capture, report, and route directories
- Configured dog names and IP addresses
- Cached ROS bridge connections
- Active waypoint patrols
- Thread locks
- Phase 1 command cancellation
- Emergency stop helpers

Keeping these resources here prevents different API modules from creating
their own separate copies of the same runtime state.
"""

import os
import threading
import time

from startup import dog_prep


# ---------------------------------------------------------------------------
# Project directories
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CAPTURE_DIR = os.path.join(
    BASE_DIR,
    "captures"
)

REPORT_DIR = os.path.join(
    BASE_DIR,
    "reports"
)

ROUTES_DIR = os.path.join(
    BASE_DIR,
    "routes"
)


# Make sure output directories exist.

os.makedirs(
    CAPTURE_DIR,
    exist_ok=True
)

os.makedirs(
    REPORT_DIR,
    exist_ok=True
)


# ---------------------------------------------------------------------------
# Dog configuration
# ---------------------------------------------------------------------------

# Dogs live in dogs.json
# (edited from the UI's "Add / Remove Dogs").
#
# DOG_IPS / DOG_NAMES are kept as dictionaries because multiple parts
# of the application need access to the configured dogs.

DOG_IPS = {}

DOG_NAMES = {}


def reload_dogs():
    """
    Re-read dogs.json into DOG_IPS / DOG_NAMES.

    The dictionaries are updated in place so references held by other
    modules remain valid.
    """

    dogs = dog_prep.load_dogs()

    DOG_IPS.clear()

    DOG_NAMES.clear()

    for dog in dogs:

        DOG_IPS[dog["id"]] = dog["ip"]

        DOG_NAMES[dog["id"]] = dog["name"]

    return dogs


# Load configured dogs when the backend starts.

reload_dogs()


# ---------------------------------------------------------------------------
# ROS bridge connections
# ---------------------------------------------------------------------------

# Cache one ROS bridge per dog so every API request does not create
# an entirely new rosbridge connection.

_bridges = {}

_bridge_lock = threading.Lock()


def get_bridge(dog_id):
    """
    Return a cached ROS bridge for a specific robot/dog ID.

    A new RosPugBridge is created the first time a dog is requested.
    Later calls reuse the existing bridge.
    """

    with _bridge_lock:

        if (
            dog_id not in _bridges
            or _bridges[dog_id] is None
        ):

            try:

                from ros2_bridge.ros_nodes import RosPugBridge

                ip = DOG_IPS.get(dog_id)

                name = DOG_NAMES.get(
                    dog_id,
                    dog_id
                )

                if not ip:

                    raise ValueError(
                        f"Unknown dog_id: {dog_id}"
                    )

                _bridges[dog_id] = RosPugBridge(
                    ip,
                    robot_name=name
                )

            except Exception as e:

                raise RuntimeError(
                    f"Could not connect to {dog_id}: {e}"
                )

        return _bridges[dog_id]


def clear_bridge(dog_id):
    """
    Remove a cached bridge for one dog.

    This is useful after:
    - Removing a dog
    - Re-preparing a dog
    - Restarting dog-side ROS services

    The next call to get_bridge() will create a fresh connection.
    """

    with _bridge_lock:

        return _bridges.pop(
            dog_id,
            None
        )


def clear_all_bridges():
    """
    Remove every cached ROS bridge.

    This does not modify dogs.json.
    """

    with _bridge_lock:

        _bridges.clear()


# ---------------------------------------------------------------------------
# Emergency stopping
# ---------------------------------------------------------------------------

def emergency_stop_robot(bridge):
    """
    Attempt to immediately halt the robot by repeating stop commands.

    This preserves the emergency-stop behavior that previously lived
    directly inside app.py.
    """

    try:

        # Send stop=True 15 times with minimal delay.

        for _ in range(15):

            bridge._publish(
                x=0.0,
                y=0.0,
                yaw_rate=0.0,
                stop=True
            )

            time.sleep(0.02)

        # Then call the full stop method.

        bridge.stop()

        time.sleep(0.3)

        # One more for good measure.

        bridge.stop()

    except Exception:

        # Emergency stopping should not crash the Flask backend if the
        # ROS connection has already been lost.

        pass


# ---------------------------------------------------------------------------
# Phase 1 command cancellation
# ---------------------------------------------------------------------------

# The existing Phase 1 natural-language movement system uses this event
# to stop an active command.

cancel_event = threading.Event()


# ---------------------------------------------------------------------------
# Waypoint patrol runtime
# ---------------------------------------------------------------------------

# dog_id -> RouteRunner while a patrol is running

_patrols = {}

_patrol_lock = threading.Lock()


# Runner statuses that end a patrol and how the UI should show them.

PATROL_END = {

    "route_completed": "done",

    "route_stopped": "done",

    "route_failed": "error",
}


def register_patrol(
    dog_id,
    runner
):
    """
    Register an active RouteRunner for a dog.
    """

    with _patrol_lock:

        _patrols[dog_id] = runner


def remove_patrol(dog_id):
    """
    Remove a dog from the active patrol registry.
    """

    with _patrol_lock:

        return _patrols.pop(
            dog_id,
            None
        )


def get_patrol(dog_id):
    """
    Return the active RouteRunner for a dog, if one exists.
    """

    with _patrol_lock:

        return _patrols.get(
            dog_id
        )


def is_patrolling(dog_id):
    """
    Return True when the dog currently has an active RouteRunner.
    """

    with _patrol_lock:

        return dog_id in _patrols


def stop_patrol(dog_id):
    """
    Cancel a running patrol for this dog, if one exists.

    Returns True if a patrol was running.
    """

    runner = get_patrol(
        dog_id
    )

    if runner:

        runner.stop()

        return True

    return False


# ---------------------------------------------------------------------------
# Patrol image filename helper
# ---------------------------------------------------------------------------

def safe_name(text):
    """
    Convert waypoint names into filename-safe labels.

    Example:

        "Stop 9 (return)"

    becomes:

        "Stop-9-return"
    """

    keep = "".join(
        char if char.isalnum() else "-"
        for char in text
    )

    return "-".join(
        part
        for part in keep.split("-")
        if part
    )