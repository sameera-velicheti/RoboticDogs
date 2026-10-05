"""Tests for route loading and the route runner. No robot needed.

Run from the repo root:  python -m pytest tests/
"""

import copy

import pytest

from navigation.navigator import MockNavigator, quaternion_to_yaw, yaw_to_quaternion
from navigation.route_loader import RouteError, load_route, validate_route
from navigation.route_runner import RouteRunner

ROUTE = {
    "route_name": "Test",
    "waypoints": [
        {"name": "A", "x": 1, "y": 0, "yaw": 0, "action": "capture_image"},
        {"name": "B", "x": 2, "y": 0, "yaw": 0, "action": "capture_image", "required": False},
        {"name": "C", "x": 3, "y": 0, "yaw": 0, "action": "none"},
    ],
}


def route():
    return validate_route(copy.deepcopy(ROUTE))


def run(nav, r=None):
    events = []
    runner = RouteRunner(nav, "Pumbaa", capture=lambda: "img.jpg", on_event=events.append)
    return runner.run(r or route()), events, runner


# --- loader ---

def test_route_files_in_repo_are_valid():
    load_route("routes/ops_center.json")
    load_route("routes/data_center.json")


def test_defaults_filled_in():
    wp = route()["waypoints"][0]
    assert wp["required"] is True and wp["retries"] == 2


def test_missing_field_rejected():
    bad = copy.deepcopy(ROUTE)
    del bad["waypoints"][0]["yaw"]
    with pytest.raises(RouteError, match="yaw"):
        validate_route(bad)


def test_duplicate_name_rejected():
    bad = copy.deepcopy(ROUTE)
    bad["waypoints"][1]["name"] = "A"
    with pytest.raises(RouteError, match="Duplicate"):
        validate_route(bad)


def test_unknown_action_rejected():
    bad = copy.deepcopy(ROUTE)
    bad["waypoints"][0]["action"] = "dance"
    with pytest.raises(RouteError, match="dance"):
        validate_route(bad)


# --- runner ---

def test_full_route_completes_and_captures():
    summary, events, _ = run(MockNavigator(travel_time=0))
    assert summary["completed"]
    assert summary["reached"] == ["A", "B", "C"]
    assert summary["images"] == ["img.jpg", "img.jpg"]  # C has no photo
    assert events[-1]["status"] == "route_completed"


def test_optional_waypoint_skipped_when_unreachable():
    summary, events, _ = run(MockNavigator(travel_time=0, fail_at={(2, 0)}))
    assert summary["completed"]
    assert summary["skipped"] == ["B"]
    # B was tried 1 + 2 retries = 3 times
    assert sum(e["status"] == "navigating" and e["waypoint_name"] == "B" for e in events) == 3


def test_required_waypoint_failure_ends_route():
    summary, events, _ = run(MockNavigator(travel_time=0, fail_at={(1, 0)}))
    assert not summary["completed"]
    assert summary["reached"] == []
    assert events[-1]["status"] == "route_failed"


def test_capture_failure_does_not_end_route():
    def broken_camera():
        raise RuntimeError("No image received")
    events = []
    runner = RouteRunner(MockNavigator(travel_time=0), capture=broken_camera,
                         on_event=events.append)
    summary = runner.run(route())
    assert summary["completed"]
    assert any(e["status"] == "capture_failed" for e in events)


def test_stop_ends_route():
    events = []

    def on_event(e):
        events.append(e)
        if e["status"] == "arrived":
            runner.stop()

    runner = RouteRunner(MockNavigator(travel_time=0), on_event=on_event)
    summary = runner.run(route())
    assert not summary["completed"]
    assert events[-1]["status"] == "route_stopped"


def test_events_have_ui_fields():
    _, events, _ = run(MockNavigator(travel_time=0))
    for e in events:
        assert {"dog", "status", "waypoint", "total", "waypoint_name"} <= e.keys()


# --- helpers ---

@pytest.mark.parametrize("yaw", [0.0, 1.571, -1.571, 3.0])
def test_yaw_round_trip(yaw):
    assert quaternion_to_yaw(yaw_to_quaternion(yaw)) == pytest.approx(yaw, abs=1e-6)


# --- RosNavigator with a fake rosbridge connection ---

class FakeTopic:
    registry = {}

    def __init__(self, client, name, msg_type):
        self.name, self.published, self.callback = name, [], None
        FakeTopic.registry[name] = self

    def publish(self, msg):
        self.published.append(dict(msg))
        if self.name.endswith("/goal") and FakeTopic.reply is not None:
            goal_id = msg["goal_id"]["id"]
            FakeTopic.registry["/move_base/result"].callback(
                {"status": {"goal_id": {"id": goal_id}, "status": FakeTopic.reply}})

    def subscribe(self, cb):
        self.callback = cb

    def unsubscribe(self):
        pass


@pytest.fixture
def ros_nav(monkeypatch):
    import roslibpy
    from navigation.navigator import RosNavigator
    monkeypatch.setattr(roslibpy, "Topic", FakeTopic)
    FakeTopic.registry = {}
    return RosNavigator(ros_client=object())


def test_ros_goal_message_and_success(ros_nav):
    FakeTopic.reply = 3  # SUCCEEDED
    result = ros_nav.go_to(1.5, -2.0, 1.571, timeout=1)
    assert result.success
    goal = FakeTopic.registry["/move_base/goal"].published[0]
    pose = goal["goal"]["target_pose"]
    assert pose["header"]["frame_id"] == "map"
    assert pose["pose"]["position"] == {"x": 1.5, "y": -2.0, "z": 0.0}


def test_ros_aborted_goal_fails(ros_nav):
    FakeTopic.reply = 4  # ABORTED
    result = ros_nav.go_to(0, 0, 0, timeout=1)
    assert not result.success and "aborted" in result.message


def test_ros_timeout_cancels_goal(ros_nav):
    FakeTopic.reply = None  # move_base never answers
    result = ros_nav.go_to(0, 0, 0, timeout=0.1)
    assert not result.success and "Timed out" in result.message
    assert FakeTopic.registry["/move_base/cancel"].published