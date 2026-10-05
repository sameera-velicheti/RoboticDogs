"""Record waypoints by walking the dog to each spot.

Run from the repo's top folder on the GB10, while the dog is localized on the
saved map (map_server + amcl running on the dog):

    python tools/record_waypoints.py --ip 192.168.0.60 --out routes/ops_center.json

Walk or drive the dog to a spot, press Enter, type a name. The dog's current
map position is saved as a waypoint in the same format as routes/*.json.
Type q to finish. Re-running with the same --out file adds to the end.
"""

import argparse
import json
import math
import os
import time


def quaternion_to_yaw(q):
    """Convert a ROS quaternion to a heading in radians."""
    siny = 2.0 * (q["w"] * q["z"] + q["x"] * q["y"])
    cosy = 1.0 - 2.0 * (q["y"] ** 2 + q["z"] ** 2)
    return math.atan2(siny, cosy)


def main():
    parser = argparse.ArgumentParser(description="Record waypoints from the dog's position")
    parser.add_argument("--ip", required=True, help="dog IP, e.g. 192.168.0.60 (Pumbaa)")
    parser.add_argument("--out", required=True, help="route JSON file to write")
    parser.add_argument("--route-name", default="Operations Center Patrol")
    parser.add_argument("--pose-topic", default="/amcl_pose")
    args = parser.parse_args()

    import roslibpy

    if os.path.exists(args.out):
        with open(args.out) as f:
            route = json.load(f)
        print(f"Adding to existing route with {len(route['waypoints'])} waypoint(s)")
    else:
        route = {"route_name": args.route_name, "waypoints": []}

    client = roslibpy.Ros(host=args.ip, port=9090)
    client.run()
    pose = {"latest": None}
    sub = roslibpy.Topic(client, args.pose_topic,
                         "geometry_msgs/PoseWithCovarianceStamped")
    sub.subscribe(lambda msg: pose.__setitem__("latest", msg["pose"]["pose"]))

    print("Waiting for a position from amcl...")
    for _ in range(50):
        if pose["latest"]:
            break
        time.sleep(0.1)
    if not pose["latest"]:
        print("No position received. Is amcl running and the map loaded?")
        print("(amcl only publishes after the dog moves or you set 2D Pose Estimate in RViz)")

    try:
        while True:
            cmd = input("\nEnter = record here, q = save and quit: ").strip().lower()
            if cmd == "q":
                break
            p = pose["latest"]
            if not p:
                print("No position yet, move the dog a little and try again.")
                continue

            x = round(p["position"]["x"], 3)
            y = round(p["position"]["y"], 3)
            yaw = round(quaternion_to_yaw(p["orientation"]), 3)

            default_name = f"Checkpoint{len(route['waypoints']) + 1}"
            name = input(f"Name [{default_name}]: ").strip() or default_name
            capture = input("Take a photo here? [Y/n]: ").strip().lower() != "n"
            required = input("Required stop? [Y/n]: ").strip().lower() != "n"

            route["waypoints"].append({
                "name": name, "x": x, "y": y, "yaw": yaw,
                "action": "capture_image" if capture else "none",
                "required": required,
            })
            print(f"Saved {name} at x={x}, y={y}, yaw={yaw}")

            with open(args.out, "w") as f:  # save after every point
                json.dump(route, f, indent=4)
    finally:
        sub.unsubscribe()
        client.terminate()
        print(f"\n{len(route['waypoints'])} waypoint(s) in {args.out}")


if __name__ == "__main__":
    main()