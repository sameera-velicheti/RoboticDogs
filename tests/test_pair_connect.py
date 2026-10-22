"""Pair & Connect: app mode vs patrol mode, fixing the dog's clock, and the camera."""

import re
import time

import pytest

from startup import dog_prep

DOG = {"id": "dog1", "name": "Pumbaa", "ip": "192.168.0.60",
       "ssh_user": "hiwonder", "ros_port": 9090}

APP_MODE = "/rosbridge_websocket\n/pug_control\n"
PATROL = "/amcl\n/move_base_node\n/rosbridge_websocket\n/map_server\n"
CLOCK_2023 = 1677764476          # Thu Mar 2 2023, what the dogs reset to


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    dog_prep._verified.clear()
    monkeypatch.setattr(dog_prep, "port_open", lambda ip, port, timeout=0.6: True)
    monkeypatch.setattr(dog_prep.time, "sleep", lambda s: None)


def fake_dog(monkeypatch, nodes, clock, camera=True, camera_after_launch=True):
    """Pretend dog: answers SSH commands, remembers what was run."""
    state = {"nodes": nodes, "clock": clock, "ran": [], "camera": camera,
             "camera_after_launch": camera_after_launch}

    def ssh(dog, command, timeout=30):
        state["ran"].append(command)
        if command.startswith("sudo -n date -s @"):
            state["clock"] = int(command.split("@")[1])
            return True, ""
        if "patrol.launch" in command:
            state["nodes"] = PATROL
            state["camera"] = state["camera_after_launch"]
            return True, ""
        if "pkill" in command:
            state["nodes"] = ""
            state["camera"] = False
            return True, ""
        if "rostopic hz" in command:
            if state["camera"] and state["nodes"]:
                return False, "subscribed to [/csi_camera/image_color/compressed]\naverage rate: 31.3"
            return False, "subscribed to [/csi_camera/image_color/compressed]\nno new messages"
        if "CLOCK=" in command:
            return True, state["nodes"] + f"CLOCK={state['clock']}"
        if command == "rosnode list":
            return True, state["nodes"]
        return True, ""

    monkeypatch.setattr(dog_prep, "_ssh", ssh)
    return state


def test_app_mode_is_not_shown_as_ready():
    # Port 9090 open because app mode runs rosbridge, but never paired.
    assert dog_prep.dog_status(DOG)[0] == "online"


def test_app_mode_runs_all_steps_and_sets_clock_before_launch(monkeypatch):
    dog = fake_dog(monkeypatch, APP_MODE, CLOCK_2023)
    updates = list(dog_prep.prepare_dog(DOG))

    assert updates[-1] == {"done": True, "ok": True, "msg": "Ready for patrol"}
    clock_step = next(i for i, c in enumerate(dog["ran"]) if "date -s" in c)
    launch_step = next(i for i, c in enumerate(dog["ran"]) if "patrol.launch" in c)
    assert clock_step < launch_step
    assert abs(dog["clock"] - time.time()) < 5
    assert dog_prep.dog_status(DOG)[0] == "ready"


def test_patrol_mode_with_wrong_clock_is_restarted(monkeypatch):
    dog = fake_dog(monkeypatch, PATROL, CLOCK_2023)
    updates = list(dog_prep.prepare_dog(DOG))

    assert updates[-1]["ok"]
    assert any("date -s" in c for c in dog["ran"])
    assert any("patrol.launch" in c for c in dog["ran"])


def test_patrol_mode_with_right_clock_is_left_alone(monkeypatch):
    dog = fake_dog(monkeypatch, PATROL, int(time.time()))
    updates = list(dog_prep.prepare_dog(DOG))

    assert updates == [{"done": True, "ok": True, "msg": "Already in patrol mode"}]
    assert not any("patrol.launch" in c for c in dog["ran"])
    assert dog_prep.dog_status(DOG)[0] == "ready"


def test_dog_going_offline_forgets_ready(monkeypatch):
    dog_prep._verified.add("dog1")
    monkeypatch.setattr(dog_prep, "port_open", lambda ip, port, timeout=0.6: False)
    assert dog_prep.dog_status(DOG)[0] == "offline"
    assert "dog1" not in dog_prep._verified


def test_camera_service_is_reset_before_launch(monkeypatch):
    dog = fake_dog(monkeypatch, APP_MODE, CLOCK_2023)
    list(dog_prep.prepare_dog(DOG))

    reset = next(i for i, c in enumerate(dog["ran"]) if "nvargus-daemon" in c)
    launch = next(i for i, c in enumerate(dog["ran"]) if "patrol.launch" in c)
    assert reset < launch


def test_patrol_mode_with_dead_camera_is_restarted(monkeypatch):
    # What happened to Pumbaa on 10/22: navigation up, camera never started.
    dog = fake_dog(monkeypatch, PATROL, int(time.time()), camera=False)
    updates = list(dog_prep.prepare_dog(DOG))

    assert updates[-1]["ok"]
    assert any("nvargus-daemon" in c for c in dog["ran"])
    assert any("patrol.launch" in c for c in dog["ran"])


def test_camera_that_never_starts_fails_pair_and_connect(monkeypatch):
    dog = fake_dog(monkeypatch, APP_MODE, CLOCK_2023, camera_after_launch=False)
    updates = list(dog_prep.prepare_dog(DOG))

    assert updates[-1]["ok"] is False
    assert "camera" in updates[-1]["msg"]
    assert dog_prep.dog_status(DOG)[0] != "ready"


def test_clear_step_does_not_kill_its_own_ssh_shell():
    # pkill -f matches full command lines, including the shell running this
    # command. None of the patterns may match the command's own text.
    cmd = dog_prep.CLEAR_AND_RESET_CAMERA
    for pattern in re.findall(r"-f '([^']+)'", cmd):
        assert re.search(pattern, cmd) is None, pattern