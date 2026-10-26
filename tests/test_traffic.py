"""Two dogs in one aisle keep right to pass each other."""

import time

import pytest

from navigation import traffic
from navigation.navigator import MockNavigator
from navigation.route_runner import RouteRunner


@pytest.fixture(autouse=True)
def clean():
    traffic._poses.clear()
    traffic._topics.clear()
    yield
    traffic._poses.clear()


# The aisle runs along x at y = -0.45 (like data_center.json).
Y = -0.45


def test_no_other_dog_goal_unchanged():
    traffic.update_pose("dog1", 2.0, Y)
    assert traffic.adjust_goal("dog1", 4.0, Y, 0.0) == (4.0, Y, 0.0, None)


def test_head_on_both_dogs_keep_to_their_own_right():
    traffic.update_pose("dog1", 5.0, Y)     # Pumbaa walking +x
    traffic.update_pose("dog2", 8.0, Y)     # Timon walking -x
    x1, y1, _, note1 = traffic.adjust_goal("dog1", 6.5, Y, 0.0, {"dog2": "Timon"})
    x2, y2, _, note2 = traffic.adjust_goal("dog2", 6.5, Y, 3.142)

    # Walking +x, right is -y. Walking -x, right is +y. Opposite sides:
    assert y1 == pytest.approx(Y - traffic.PASS_OFFSET)
    assert y2 == pytest.approx(Y + traffic.PASS_OFFSET)
    assert y2 - y1 == pytest.approx(2 * traffic.PASS_OFFSET)
    assert x1 == 6.5 and x2 == 6.5            # still heading to the same stop spot
    assert note1 == "Keeping right to pass Timon"


def test_dog_behind_is_ignored():
    traffic.update_pose("dog1", 5.0, Y)
    traffic.update_pose("dog2", 3.0, Y)     # behind dog1
    assert traffic.adjust_goal("dog1", 6.5, Y, 0.0)[3] is None


def test_far_away_dog_is_ignored():
    traffic.update_pose("dog1", 1.0, Y)
    traffic.update_pose("dog2", 1.0 + traffic.LOOKAHEAD + 1, Y)
    assert traffic.adjust_goal("dog1", 2.5, Y, 0.0)[3] is None


def test_dog_in_another_aisle_is_ignored():
    traffic.update_pose("dog1", 5.0, Y)
    traffic.update_pose("dog2", 7.0, Y + 3.0)   # a different aisle
    assert traffic.adjust_goal("dog1", 6.5, Y, 0.0)[3] is None


def test_stale_position_is_ignored(monkeypatch):
    traffic.update_pose("dog1", 5.0, Y)
    traffic.update_pose("dog2", 7.0, Y)
    later = time.time() + traffic.STALE_SECONDS + 1
    monkeypatch.setattr(traffic.time, "time", lambda: later)
    assert traffic.adjust_goal("dog1", 6.5, Y, 0.0)[3] is None


def test_route_runner_sends_the_shifted_goal_and_keeps_going():
    sent = []

    class Nav(MockNavigator):
        def go_to(self, x, y, yaw, timeout=60.0):
            sent.append((x, y))
            return super().go_to(x, y, yaw, timeout)

    route = {"route_name": "T", "waypoints": [
        {"name": "A", "x": 1.0, "y": Y, "yaw": 0.0, "action": "none", "required": True, "retries": 0},
        {"name": "B", "x": 2.0, "y": Y, "yaw": 0.0, "action": "none", "required": True, "retries": 0}]}
    events = []
    shift = lambda x, y, yaw: (x, y - 0.4, yaw, "Keeping right to pass Timon")
    RouteRunner(Nav(travel_time=0), adjust_goal=shift, on_event=events.append).run(route)

    assert sent == [(1.0, Y - 0.4), (2.0, Y - 0.4)]
    assert events[-1]["status"] == "route_completed"        # never stopped
    assert any(e["message"] == "Keeping right to pass Timon" for e in events)


def test_broken_adjuster_falls_back_to_normal_goal():
    sent = []

    class Nav(MockNavigator):
        def go_to(self, x, y, yaw, timeout=60.0):
            sent.append((x, y))
            return super().go_to(x, y, yaw, timeout)

    def broken(x, y, yaw):
        raise RuntimeError("no pose")

    route = {"route_name": "T", "waypoints": [
        {"name": "A", "x": 1.0, "y": Y, "yaw": 0.0, "action": "none", "required": True, "retries": 0}]}
    RouteRunner(Nav(travel_time=0), adjust_goal=broken, on_event=lambda e: None).run(route)
    assert sent == [(1.0, Y)]