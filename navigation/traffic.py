"""Two dogs in one aisle: keep right to pass, without stopping.

Both dogs are localized on the same map, so the app knows where each one is
(from /amcl_pose). Before a dog is sent to its next stop, adjust_goal()
checks the other dogs on patrol:

    If another dog is AHEAD of it (in the direction it is about to walk),
    in its lane, and closer than LOOKAHEAD metres, the stop is shifted
    PASS_OFFSET metres to the walking dog's RIGHT.

Both dogs apply the same rule, so when they walk toward each other they
slide to opposite sides and pass with a gap, the way people do in a
hallway. Once the other dog is behind it, stops go back to the centre line.

The dogs' own navigation (move_base + LiDAR costmap) still avoids anything
close as a safety net; this rule just stops them choosing the same side.
"""

import math
import threading
import time

LOOKAHEAD = 8.0        # m: start keeping right when the other dog is this close
                       #    (simulated: 4 m let the dogs touch in the worst timing)
LANE_WIDTH = 1.0       # m: "in my lane" = within this far to either side of my path
PASS_OFFSET = 0.5      # m: how far each dog moves over (aisle is ~1.8-2.4 m wide);
                       #    with LOOKAHEAD 8 the dogs stay >= 0.9 m apart (centre to centre)
STALE_SECONDS = 5.0    # ignore positions older than this

_poses = {}            # dog_id -> {"x", "y", "time"}
_topics = {}           # dog_id -> roslibpy.Topic
_lock = threading.Lock()


# ---------------------------------------------------------------- positions --

def update_pose(dog_id, x, y):
    with _lock:
        _poses[dog_id] = {"x": x, "y": y, "time": time.time()}


def forget(dog_id):
    """Stop tracking a dog (its patrol ended)."""
    with _lock:
        _poses.pop(dog_id, None)
        topic = _topics.pop(dog_id, None)
    if topic is not None:
        try:
            topic.unsubscribe()
        except Exception:
            pass


def track(dog_id, ros_client):
    """Follow a dog's position from /amcl_pose over its rosbridge connection."""
    import roslibpy

    with _lock:
        if dog_id in _topics:
            return

    def on_pose(message):
        p = message["pose"]["pose"]["position"]
        update_pose(dog_id, p["x"], p["y"])

    topic = roslibpy.Topic(
        ros_client, "/amcl_pose", "geometry_msgs/PoseWithCovarianceStamped")
    topic.subscribe(on_pose)

    with _lock:
        _topics[dog_id] = topic


def _fresh_pose(dog_id):
    with _lock:
        pose = _poses.get(dog_id)
    if pose and time.time() - pose["time"] <= STALE_SECONDS:
        return pose
    return None


def _other_poses(dog_id):
    with _lock:
        others = [(d, p) for d, p in _poses.items() if d != dog_id]
    now = time.time()
    return [(d, p) for d, p in others if now - p["time"] <= STALE_SECONDS]


# ------------------------------------------------------------------ passing --

def adjust_goal(dog_id, x, y, yaw, names=None):
    """Return (x, y, yaw, note): the goal, shifted right if a dog is ahead.

    note is None when nothing changed, or a short message for the UI.
    """
    me = _fresh_pose(dog_id)
    if me is None:
        return x, y, yaw, None

    # Direction I'm about to walk.
    dx, dy = x - me["x"], y - me["y"]
    length = math.hypot(dx, dy)
    if length < 0.05:
        return x, y, yaw, None
    fx, fy = dx / length, dy / length          # forward
    rx, ry = fy, -fx                           # right of forward (ROS: x fwd, y left)

    for other_id, other in _other_poses(dog_id):
        ox, oy = other["x"] - me["x"], other["y"] - me["y"]
        ahead = ox * fx + oy * fy              # distance along my path
        side = ox * rx + oy * ry               # distance to my right (+) / left (-)
        if 0 < ahead <= LOOKAHEAD and abs(side) <= LANE_WIDTH:
            return (x + rx * PASS_OFFSET, y + ry * PASS_OFFSET, yaw,
                    f"Keeping right to pass {(names or {}).get(other_id, other_id)}")

    return x, y, yaw, None