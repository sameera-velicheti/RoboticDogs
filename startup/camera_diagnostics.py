"""Save a health snapshot of a dog the moment its camera stops sending images.

Why: when a camera fails, rebooting the dog fixes it but also erases the
evidence of what went wrong. This logs into the dog over SSH (same as
Pair & Connect) right when the failure happens and saves what it finds to
    logs/camera_<Dog>_<date>_<time>.txt

It runs in the background, so the patrol/command that hit the error is not
slowed down, and at most once every few minutes per dog.

Run it by hand any time (for example, before rebooting a dog):
    python3 -m startup.camera_diagnostics Timon
"""

import os
import sys
import threading
import time
from datetime import datetime

from startup.dog_prep import _ssh, load_dogs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
CAMERA_TOPIC = "/csi_camera/image_color/compressed"
COOLDOWN_SECONDS = 180          # don't collect again for the same dog within 3 minutes

# (title, command run on the dog, what a bad result looks like)
CHECKS = [
    ("Uptime", "uptime",
     "Failures only after hours of running point to heat or memory build-up"),
    ("Memory", "free -h",
     "'available' close to 0 = out of memory"),
    ("Disk space", "df -h /",
     "Use% close to 100% = storage full (try: rosclean purge)"),
    ("Power / throttling", "vcgencmd get_throttled",
     "Anything other than throttled=0x0 = under-voltage or overheating happened"),
    ("Temperature", "vcgencmd measure_temp",
     "Above about 80'C = overheating"),
    ("Running ROS nodes", "rosnode list",
     "No camera node in the list = the camera program crashed"),
    ("Camera frame rate (on the dog)", f"timeout 6 rostopic hz {CAMERA_TOPIC}",
     "'no new messages' = camera dead. A steady rate = camera fine, problem is rosbridge/Wi-Fi"),
    ("Kernel messages", "dmesg 2>/dev/null | tail -40",
     "Lines mentioning camera, unicam, mmal or under-voltage"),
    ("Patrol log", "tail -40 ~/patrol.log",
     "Crashes or errors from navigation/rosbridge"),
]

_last_run = {}
_lock = threading.Lock()


def find_dog(name_or_ip):
    """Look a dog up in dogs.json by name, id or IP address."""
    key = str(name_or_ip).strip().lower()
    for dog in load_dogs():
        if key in (dog["name"].lower(), dog["id"].lower(), dog["ip"]):
            return dog
    return None


def _build_command():
    """One SSH session that runs every check, each under a clear heading."""
    parts = []
    for title, cmd, _ in CHECKS:
        parts.append(f"echo '===== {title} ====='; ({cmd}) 2>&1 || true; echo")
    return "; ".join(parts)


def collect(dog, reason="camera stopped sending images"):
    """Run the checks on `dog` now and save them. Returns the report path."""
    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(LOG_DIR, f"camera_{dog['name']}_{stamp}.txt")

    ok, output = _ssh(dog, _build_command(), timeout=60)

    with open(path, "w") as f:
        f.write(f"Camera diagnostics for {dog['name']} ({dog['ip']})\n")
        f.write(f"Time:   {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"Reason: {reason}\n")
        if not ok and not output.strip():
            f.write("\nCould not reach the dog over SSH, so nothing was collected.\n")
        f.write("\nWhat to look for:\n")
        for title, _, hint in CHECKS:
            f.write(f"  - {title}: {hint}\n")
        f.write("\n" + output + "\n")
    return path


def collect_in_background(name_or_ip, reason="camera stopped sending images"):
    """Start collect() in a background thread unless this dog was just checked.

    Returns True if a new report was started, False if skipped.
    """
    dog = find_dog(name_or_ip)
    if dog is None:
        return False

    with _lock:
        now = time.time()
        if now - _last_run.get(dog["id"], 0) < COOLDOWN_SECONDS:
            return False
        _last_run[dog["id"]] = now

    def run():
        try:
            path = collect(dog, reason)
            print(f"[camera diagnostics] saved {path}")
        except Exception as error:      # diagnostics must never crash the app
            print(f"[camera diagnostics] failed for {dog['name']}: {error}")

    threading.Thread(target=run, daemon=True).start()
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 -m startup.camera_diagnostics <dog name or IP>")
        sys.exit(1)
    target = find_dog(sys.argv[1])
    if target is None:
        print(f"No dog called '{sys.argv[1]}' in dogs.json")
        sys.exit(1)
    print(f"Collecting diagnostics from {target['name']}...")
    print(f"Saved: {collect(target, reason='collected by hand')}")