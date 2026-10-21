"""What happens when things go wrong during the one-route demo"""

import pytest
import requests

import runtime
from services import legacy_commands
from vision import compliance_checker


# --- DEAD rosbridge connection is replaced, not reused ---

class _Client:
    def __init__(self, connected):
        self.is_connected = connected


class _Bridge:
    def __init__(self, connected):
        self.client = _Client(connected)
        self.closed = False

    def close(self):
        self.closed = True


def test_dead_bridge_is_replaced(monkeypatch):
    dead = _Bridge(connected=False)
    fresh = _Bridge(connected=True)
    monkeypatch.setitem(runtime._bridges, "dog1", dead)

    import ros2_bridge.ros_nodes as ros_nodes
    monkeypatch.setattr(ros_nodes, "RosPugBridge",
                        lambda ip, robot_name=None: fresh)

    assert runtime.get_bridge("dog1") is fresh
    assert dead.closed


def test_live_bridge_is_reused(monkeypatch):
    live = _Bridge(connected=True)
    monkeypatch.setitem(runtime._bridges, "dog1", live)

    assert runtime.get_bridge("dog1") is live


class _CommandBridge:
    def _publish(self, **kwargs):
        pass

    def stop(self):
        pass


def _run_walk_command(monkeypatch, dog_id):
    bridge = _CommandBridge()
    monkeypatch.setattr(legacy_commands, "send_to_nim",
                        lambda prompt: '{"actions": [{"action": "walk_backward", "duration": 0.2}]}')
    monkeypatch.setattr(legacy_commands, "get_bridge",
                        lambda selected_dog: bridge)
    monkeypatch.setattr(legacy_commands, "emergency_stop_robot",
                        lambda selected_bridge: None)
    monkeypatch.setattr(legacy_commands.time, "sleep",
                        lambda duration: None)
    return legacy_commands.stream_command("walk backward", dog_id=dog_id)


def test_cancelling_one_dog_does_not_cancel_another(monkeypatch):
    runtime.get_cancel_event("dog1").clear()
    runtime.get_cancel_event("dog2").clear()
    command = _run_walk_command(monkeypatch, "dog2")

    next(command)
    runtime.get_cancel_event("dog1").set()
    output = "".join(command)

    assert runtime.get_cancel_event("dog1").is_set()
    assert '"type": "action_done"' in output
    assert '"msg": "Command stopped."' not in output


def test_new_command_clears_cancel_for_same_dog(monkeypatch):
    runtime.get_cancel_event("dog1").set()
    command = _run_walk_command(monkeypatch, "dog1")

    output = "".join(command)

    assert not runtime.get_cancel_event("dog1").is_set()
    assert '"type": "action_done"' in output
    assert '"msg": "Command stopped."' not in output


# --- Qwen problems show a clear message ---

@pytest.fixture
def image(tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"\xff\xd8fake")
    return str(path)


def test_qwen_not_running(monkeypatch, image):
    def refuse(*a, **k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(compliance_checker.requests, "post", refuse)

    with pytest.raises(RuntimeError, match="Is Qwen started"):
        compliance_checker.check_compliance_with_nim(image)


def test_qwen_too_slow(monkeypatch, image):
    def slow(*a, **k):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(compliance_checker.requests, "post", slow)

    with pytest.raises(RuntimeError, match="still be loading"):
        compliance_checker.check_compliance_with_nim(image)


def test_qwen_returns_error(monkeypatch, image):
    class Resp:
        status_code = 404
        text = '{"error": "model qwen does not exist"}'

        def json(self):
            return {"error": "model qwen does not exist"}

    monkeypatch.setattr(compliance_checker.requests, "post",
                        lambda *a, **k: Resp())

    with pytest.raises(RuntimeError, match="HTTP 404.*does not exist"):
        compliance_checker.check_compliance_with_nim(image)