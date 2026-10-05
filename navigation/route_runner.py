from waypoint_actions import (
    stop,
    face_target,
    capture_image,
    continue_route
)

from route_loader import load_route

route = load_route("routes/data_center.json")

print(route)
for waypoint in route["waypoints"]:

    print(f"Navigating to {waypoint['name']}")

    stop()

    face_target(waypoint["yaw"])

    if waypoint["action"] == "capture_image":
        capture_image()

    continue_route()