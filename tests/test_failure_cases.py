"""What happens when things go wrong during the one-route demo"""

import pytest
import requests

import runtime
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