"""Dog list (dogs.json) and "get this dog ready to patrol" over SSH.

The Pair & Connect button runs prepare_dog(), which does over SSH exactly what
we used to type by hand after `ssh hiwonder@<ip>`:

    1. stop pug_bringup.service        (the dog's normal app mode)
    2. kill leftover ROS processes     (prevents "launched twice")
    3. set the dog's clock             (it resets to 2023 after a reboot)
    4. start patrol.launch             (navigation + rosbridge, saved map)
    5. wait until patrol mode answers  (rosbridge port + move_base/amcl nodes)

One-time setup on each dog (on site), so this runs without typing passwords:
    ssh-copy-id hiwonder@<DOG_IP>
    echo 'hiwonder ALL=(ALL) NOPASSWD: /bin/systemctl, /bin/date' | \
        ssh -t hiwonder@<DOG_IP> 'sudo tee /etc/sudoers.d/pawpatrol && sudo chmod 440 /etc/sudoers.d/pawpatrol'
"""

import json
import os
import shlex
import socket
import subprocess
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOGS_FILE = os.path.join(ROOT, "dogs.json")

DEFAULT_DOGS = [
    {"id": "dog1", "name": "Pumbaa", "ip": "192.168.0.60", "ssh_user": "hiwonder", "ros_port": 9090},
    {"id": "dog2", "name": "Timon", "ip": "192.168.0.85", "ssh_user": "hiwonder", "ros_port": 9090},
]

MAP_NAME = "datacenter_01"

# Runs in the dog's own login shell (zsh on our dogs) so the ROS setup and the
# Hiwonder LIDAR/CAMERA variables from its startup files are loaded, exactly
# like a terminal you SSH'd into. setsid + nohup keep it running after SSH exits.
PATROL_LAUNCH = (f"setsid nohup roslaunch pug_navigation patrol.launch map:={MAP_NAME} "
                 f"> ~/patrol.log 2>&1 < /dev/null &")

_lock = threading.Lock()


# ---------------------------------------------------------------- dog list --

def load_dogs():
    """Dogs from dogs.json (created with Pumbaa and Timon the first time)."""
    with _lock:
        if not os.path.exists(DOGS_FILE):
            _write(DEFAULT_DOGS)
        with open(DOGS_FILE) as f:
            return json.load(f)


def _write(dogs):
    with open(DOGS_FILE, "w") as f:
        json.dump(dogs, f, indent=4)


def add_dog(name, ip, ssh_user="hiwonder", ros_port=9090):
    """Add a dog. Returns (dog, error)."""
    name, ip, ssh_user = name.strip(), ip.strip(), (ssh_user or "hiwonder").strip()
    parts = ip.split(".")
    if not name or not ip:
        return None, "Name and IP address are required"
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return None, "Enter a valid IPv4 address, e.g. 192.168.0.60"
    try:
        ros_port = int(ros_port)
        assert 1 <= ros_port <= 65535
    except (ValueError, AssertionError):
        return None, "ROS port must be a number between 1 and 65535"
    dogs = load_dogs()
    if any(d["name"].lower() == name.lower() for d in dogs):
        return None, f"A dog called {name} already exists"
    if any(d["ip"] == ip for d in dogs):
        return None, f"{ip} is already assigned to another dog"
    used = {d["id"] for d in dogs}
    n = 1
    while f"dog{n}" in used:
        n += 1
    dog = {"id": f"dog{n}", "name": name, "ip": ip, "ssh_user": ssh_user, "ros_port": ros_port}
    with _lock:
        _write(dogs + [dog])
    return dog, None


def remove_dog(dog_id):
    dogs = load_dogs()
    keep = [d for d in dogs if d["id"] != dog_id]
    if len(keep) == len(dogs):
        return False
    with _lock:
        _write(keep)
    return True


# ------------------------------------------------------------ status checks --

def port_open(ip, port, timeout=0.6):
    """True if something is listening on ip:port (quick TCP connect)."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def dog_status(dog):
    """offline / online (on, patrol mode not started) / ready (patrol mode up)."""
    if port_open(dog["ip"], dog.get("ros_port", 9090)):
        return "ready", "Ready for patrol"
    if port_open(dog["ip"], 22):
        return "online", "On · press Pair & Connect to start patrol mode"
    return "offline", "Offline · check the dog is on and on the TP-Link WiFi"


# ----------------------------------------------------------------- ssh prep --

def _ssh(dog, command, timeout=30):
    """Run a command on the dog in its login shell. Returns (ok, output)."""
    target = f"{dog.get('ssh_user', 'hiwonder')}@{dog['ip']}"
    remote = "exec $SHELL -lic " + shlex.quote(command)
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             "-o", "StrictHostKeyChecking=accept-new", target, remote],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except FileNotFoundError:
        return False, "ssh is not installed on this computer"
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, out


def _explain(out):
    """Turn a raw SSH/sudo error into something an operator can act on."""
    low = out.lower()
    if "permission denied" in low or "publickey" in low:
        return "SSH key not set up for this dog (one-time: ssh-copy-id hiwonder@<ip>)"
    if "a password is required" in low or "sudo:" in low:
        return "The dog asked for a sudo password (one-time sudoers setup needed)"
    if "no route to host" in low or "timed out" in low or "unreachable" in low:
        return "Can't reach the dog: is it on and on the TP-Link WiFi?"
    if "connection refused" in low:
        return "The dog refused SSH: is it still booting?"
    return out.splitlines()[-1][:160] if out else "Unknown error"


def prepare_dog(dog, ready_timeout=90):
    """Get a dog into patrol mode. Yields progress dicts for the UI:
        {"step": 1-5, "total": 5, "status": "running"|"ok"|"fail", "msg": "..."}
    The last item is {"done": True, "ok": bool, "msg": "..."}.
    """
    total = 5

    def step(n, status, msg):
        return {"step": n, "total": total, "status": status, "msg": msg}

    if port_open(dog["ip"], dog.get("ros_port", 9090)):
        yield {"done": True, "ok": True, "msg": "Already in patrol mode"}
        return

    yield step(1, "running", "Connecting and stopping the dog's app mode...")
    ok, out = _ssh(dog, "sudo -n systemctl stop pug_bringup.service")
    if not ok:
        yield step(1, "fail", _explain(out))
        yield {"done": True, "ok": False, "msg": _explain(out)}
        return
    yield step(1, "ok", "App mode stopped")

    yield step(2, "running", "Clearing leftover ROS processes...")
    _ssh(dog, "pkill -f roslaunch; pkill -f rosmaster; sleep 4; true")
    yield step(2, "ok", "Cleared")

    yield step(3, "running", "Setting the dog's clock...")
    ok, out = _ssh(dog, f"sudo -n date -s @{int(time.time())}")
    yield step(3, "ok" if ok else "fail", "Clock set" if ok else
               f"Couldn't set the clock ({_explain(out)}); continuing")

    yield step(4, "running", "Starting patrol mode (map, navigation, rosbridge)...")
    ok, out = _ssh(dog, PATROL_LAUNCH)
    if not ok:
        yield step(4, "fail", _explain(out))
        yield {"done": True, "ok": False, "msg": _explain(out)}
        return
    yield step(4, "ok", "Patrol mode launched")

    yield step(5, "running", "Waiting for navigation and rosbridge to come up...")
    deadline = time.time() + ready_timeout
    while time.time() < deadline:
        if port_open(dog["ip"], dog.get("ros_port", 9090)):
            ok, out = _ssh(dog, "rosnode list")
            missing = [n for n in ("/move_base_node", "/amcl") if n not in out]
            if ok and not missing:
                yield step(5, "ok", "Navigation and rosbridge are up")
                yield {"done": True, "ok": True, "msg": "Ready for patrol"}
                return
        time.sleep(3)

    _, log = _ssh(dog, "tail -5 ~/patrol.log")
    msg = "Patrol mode didn't come up in time"
    if "same name" in log:
        msg += " (launched twice; press Pair & Connect again)"
    elif "lidar" in log.lower():
        msg += " (LiDAR problem; power-cycle the dog)"
    yield step(5, "fail", msg)
    yield {"done": True, "ok": False, "msg": msg}