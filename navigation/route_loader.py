"""Loads route JSON files and checks they are complete before a run starts."""

import json

VALID_ACTIONS = {"capture_image", "none"}


class RouteError(ValueError):
    """Raised when a route file is missing fields or has bad values."""


def load_route(route_file):
    """Load a route file, fill in defaults and validate it."""
    with open(route_file, "r") as f:
        route = json.load(f)
    return validate_route(route)


def validate_route(route):
    """Check a route dict and fill in optional fields.

    Each waypoint needs: name, x, y, yaw, action.
    Optional per waypoint: required (default True), retries (default 2).
    """
    if "waypoints" not in route or not route["waypoints"]:
        raise RouteError("Route has no waypoints")

    route.setdefault("route_name", "Unnamed route")

    # Optional: where the dog starts (the taped spot), used to localize it
    # automatically instead of clicking "2D Pose Estimate" in RViz.
    start = route.get("start_pose")
    if start is not None:
        for field in ("x", "y", "yaw"):
            if not isinstance(start.get(field), (int, float)):
                raise RouteError(f"start_pose: '{field}' must be a number")

    seen = set()

    for i, wp in enumerate(route["waypoints"]):
        where = f"waypoint #{i + 1}"
        for field in ("name", "x", "y", "yaw", "action"):
            if field not in wp:
                raise RouteError(f"{where} is missing '{field}'")

        if wp["name"] in seen:
            raise RouteError(f"Duplicate waypoint name '{wp['name']}'")
        seen.add(wp["name"])

        for field in ("x", "y", "yaw"):
            if not isinstance(wp[field], (int, float)):
                raise RouteError(f"{wp['name']}: '{field}' must be a number")

        if wp["action"] not in VALID_ACTIONS:
            raise RouteError(
                f"{wp['name']}: unknown action '{wp['action']}' "
                f"(use one of {sorted(VALID_ACTIONS)})"
            )

        wp.setdefault("required", True)
        wp.setdefault("retries", 2)

    return route