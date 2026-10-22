"""Camera diagnostics: a fake camera failure should save a health report."""
import os

import pytest

import startup.camera_diagnostics as diag


@pytest.fixture
def fake_dog(tmp_path, monkeypatch):
    """Pretend SSH: record the command, return canned output. Logs go to a temp folder."""
    calls = []

    def fake_ssh(dog, command, timeout=30):
        calls.append((dog["name"], command))
        return True, "===== Power / throttling =====\nthrottled=0x50005\n"

    monkeypatch.setattr(diag, "_ssh", fake_ssh)
    monkeypatch.setattr(diag, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(diag, "load_dogs", lambda: [
        {"id": "dog2", "name": "Timon", "ip": "192.168.0.85", "ssh_user": "hiwonder"}])
    diag._last_run.clear()
    return calls, tmp_path


def test_report_is_saved_with_every_check(fake_dog):
    calls, folder = fake_dog
    path = diag.collect(diag.find_dog("Timon"), reason="test")
    text = open(path).read()
    assert os.path.basename(path).startswith("camera_Timon_")
    assert "Reason: test" in text and "throttled=0x50005" in text
    for title, cmd, _ in diag.CHECKS:          # every check was sent in one SSH call
        assert title in calls[0][1] and cmd in calls[0][1]


def test_dog_found_by_name_id_or_ip(fake_dog):
    for key in ("Timon", "timon", "dog2", "192.168.0.85"):
        assert diag.find_dog(key)["name"] == "Timon"
    assert diag.find_dog("Simba") is None


def test_background_run_has_cooldown(fake_dog, monkeypatch):
    calls, _ = fake_dog
    started = []
    monkeypatch.setattr(diag.threading, "Thread",
                        lambda target, daemon: type("T", (), {"start": lambda s: started.append(target)})())
    assert diag.collect_in_background("192.168.0.85") is True
    assert diag.collect_in_background("192.168.0.85") is False   # within cooldown: skipped
    started[0]()                                                   # run the saved job
    assert len(calls) == 1


def test_unreachable_dog_still_writes_report(fake_dog, monkeypatch):
    monkeypatch.setattr(diag, "_ssh", lambda dog, cmd, timeout=30: (False, ""))
    text = open(diag.collect(diag.find_dog("Timon"))).read()
    assert "Could not reach the dog" in text


def test_camera_failure_triggers_diagnostics(monkeypatch):
    """take_picture() with no frames should start diagnostics, then raise as before."""
    import ros2_bridge.ros_nodes as ros_nodes

    class SilentTopic:                      # a camera topic that never sends a frame
        def __init__(self, *a): pass
        def subscribe(self, cb): pass
        def unsubscribe(self): pass

    triggered = []
    monkeypatch.setattr(ros_nodes.roslibpy, "Topic", SilentTopic)
    monkeypatch.setattr(ros_nodes.time, "sleep", lambda s: None)
    monkeypatch.setattr(diag, "collect_in_background",
                        lambda ip, reason="": triggered.append(ip) or True)

    bridge = object.__new__(ros_nodes.RosPugBridge)
    bridge.client, bridge.robot_ip, bridge.robot_name = None, "192.168.0.85", "Timon"

    with pytest.raises(RuntimeError, match="No image received"):
        bridge.take_picture(save_dir="/tmp")
    assert triggered == ["192.168.0.85"]