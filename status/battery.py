"""Dog battery level.

The Hiwonder controller publishes the battery voltage in millivolts on
/ros_robot_controller/battery (std_msgs/UInt16), e.g. 10247 = 10.25 V.

Our dogs use a 3-cell (3S) lithium battery: about 12.6 V full, 9.6 V empty.
Lithium voltage isn't linear with charge, so the percentage comes from a
per-cell discharge curve instead of a straight line.

The reading dips while the motors work, so a walking dog can show a few
percent lower than a resting one. Readings are smoothed over ~10 seconds.
"""

import threading
import time
from collections import deque

from runtime import get_bridge

TOPIC = "/ros_robot_controller/battery"
MSG_TYPE = "std_msgs/UInt16"

CELLS = 3
LOW_PERCENT = 20

# (volts per cell, percent), highest first. Typical LiPo resting curve.
CURVE = [
    (4.20, 100), (4.10, 90), (4.00, 80), (3.92, 70), (3.86, 60),
    (3.82, 50), (3.79, 40), (3.75, 30), (3.71, 20), (3.65, 10),
    (3.50, 5), (3.20, 0),
]

# Ignore readings older than this (topic stopped / dog went away).
STALE_SECONDS = 30

_readings = {}       # dog_id -> deque of (time, millivolts)
_watching = {}       # dog_id -> time the subscription was started
_lock = threading.Lock()


def volts_to_percent(volts, cells=CELLS):
    """Pack voltage -> 0-100 using the per-cell curve."""
    per_cell = volts / cells

    if per_cell >= CURVE[0][0]:
        return 100
    if per_cell <= CURVE[-1][0]:
        return 0

    for (v_hi, p_hi), (v_lo, p_lo) in zip(CURVE, CURVE[1:]):
        if v_lo <= per_cell <= v_hi:
            fraction = (per_cell - v_lo) / (v_hi - v_lo)
            return round(p_lo + fraction * (p_hi - p_lo))

    return 0


def _record(dog_id, millivolts):
    now = time.time()
    with _lock:
        samples = _readings.setdefault(dog_id, deque())
        samples.append((now, millivolts))
        while samples and now - samples[0][0] > 10:
            samples.popleft()


def _subscribe(dog_id):
    """Background: connect to the dog's rosbridge and listen for battery."""
    try:
        import roslibpy

        bridge = get_bridge(dog_id)
        topic = roslibpy.Topic(bridge.client, TOPIC, MSG_TYPE)
        topic.subscribe(lambda msg: _record(dog_id, msg.get("data", 0)))
    except Exception:
        # Dog not reachable; try again on the next status poll.
        with _lock:
            _watching.pop(dog_id, None)


def watch(dog_id):
    """Start listening for this dog's battery, without blocking the caller."""
    now = time.time()
    with _lock:
        started = _watching.get(dog_id)
        samples = _readings.get(dog_id)
        last = samples[-1][0] if samples else 0
        # Already subscribed and either getting data or still connecting.
        if started and (now - last < STALE_SECONDS or now - started < STALE_SECONDS):
            return
        # New dog, or the old connection went quiet (dog rebooted, app
        # replaced a dead bridge): subscribe again.
        _watching[dog_id] = now
    threading.Thread(target=_subscribe, args=(dog_id,), daemon=True).start()


def forget(dog_id):
    """Drop the subscription/readings (dog went offline)."""
    with _lock:
        _watching.pop(dog_id, None)
        _readings.pop(dog_id, None)


def battery(dog_id):
    """{"percent", "volts", "low"} for the dog, or None if no recent reading."""
    with _lock:
        samples = list(_readings.get(dog_id, ()))

    if not samples or time.time() - samples[-1][0] > STALE_SECONDS:
        return None

    volts = sum(mv for _, mv in samples) / len(samples) / 1000.0
    percent = volts_to_percent(volts)

    return {
        "percent": percent,
        "volts": round(volts, 2),
        "low": percent <= LOW_PERCENT,
    }