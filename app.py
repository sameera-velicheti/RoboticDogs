"""
NemoClaw UI - Flask backend
Drop this into your RoboticDogs/ root folder and run:
    pip install flask
    python3 app.py
Then open http://localhost:5000 in your browser.
"""

import os
from datetime import datetime
from flask import Flask, render_template, request, Response, stream_with_context, send_from_directory
import json
import time
import threading
import requests as http_requests
from status.system_status import status

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURE_DIR = os.path.join(BASE_DIR, "captures")
REPORT_DIR = os.path.join(BASE_DIR, "reports")
os.makedirs(CAPTURE_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# Model server settings live in config_nim.yaml (see nim_config.py)
from nim_config import NIM_URL, NIM_MODEL, headers as nim_headers, extract_answer, extra_params

ALLOWED_ACTIONS = {"cautious_walk", "walk_backward", "sit", "stop", "turn_left", "turn_right", "take_picture"}# Build a set of user-facing keywords to match common input variants
ALLOWED_KEYWORDS = set()
for a in ALLOWED_ACTIONS:
    ALLOWED_KEYWORDS.add(a)
    spaced = a.replace("_", " ")
    ALLOWED_KEYWORDS.add(spaced)
    for part in a.split("_"):
        ALLOWED_KEYWORDS.add(part)
MAX_SPEED = 0.15
SAFE_DISTANCE = 0.5  # meters — stop if anything within this distance ahead

_bridges = {}
_bridge_lock = threading.Lock()
cancel_event = threading.Event()

# Dogs live in dogs.json (edited from the UI's "Add / Remove Dogs").
# DOG_IPS / DOG_NAMES are kept as dicts because the rest of the app uses them.
from startup import dog_prep
DOG_IPS, DOG_NAMES = {}, {}


def reload_dogs():
    """Re-read dogs.json into DOG_IPS / DOG_NAMES (in place, so references stay valid)."""
    dogs = dog_prep.load_dogs()
    DOG_IPS.clear()
    DOG_NAMES.clear()
    for d in dogs:
        DOG_IPS[d["id"]] = d["ip"]
        DOG_NAMES[d["id"]] = d["name"]
    return dogs


reload_dogs()

def get_bridge(dog_id):
    """Return a cached ROS bridge for a specific robot/dog ID."""
    global _bridges
    with _bridge_lock:
        if dog_id not in _bridges or _bridges[dog_id] is None:
            try:
                from ros2_bridge.ros_nodes import RosPugBridge
                ip = DOG_IPS.get(dog_id)
                name = DOG_NAMES.get(dog_id, dog_id)
                if not ip:
                    raise ValueError(f"Unknown dog_id: {dog_id}")
                _bridges[dog_id] = RosPugBridge(ip, robot_name=name)
            except Exception as e:
                raise RuntimeError(f"Could not connect to {dog_id}: {e}")
        return _bridges[dog_id]
    
def get_prompt(user_instruction):
    """Build the prompt text for the NIM model from user instructions."""
    return f"""
Return ONLY valid JSON. No explanation, no markdown, no extra text.

Allowed actions: cautious_walk, walk_backward, sit, stop, turn_left, turn_right, take_picture

Rules:
- Always include speed and duration for movement actions
- If given multiple actions, complete one full movement before starting the next
- Default speed is 0.10, default duration is 3.0
- Use the exact duration the user specifies if they mention seconds
- There is no maximum duration, maximum speed is 0.15
- Users should not enter unrelated instructions or questions; only robot movement commands are allowed

Return a list of actions in order:
{{"actions": [
    {{"action": "<action>", "speed": <float>, "duration": <float>}},
    {{"action": "<action>", "speed": <float>, "duration": <float>}}
]}}

User instruction: {user_instruction}
"""


def send_to_nim(prompt):
    """Send a prompt payload to the NIM inference endpoint and return the raw response."""
    payload = {
        "model": NIM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        **extra_params(),
    }
    r = http_requests.post(NIM_URL, json=payload, headers=nim_headers(), timeout=60)
    data = r.json()
    return extract_answer(data["choices"][0]["message"])


def validate_and_clamp(action):
    """Validate that the model action is allowed and clamp numeric values to safety bounds."""
    if action.get("action") not in ALLOWED_ACTIONS:
        raise ValueError(f"Invalid action: {action.get('action')}")
    if "speed" in action:
        action["speed"] = min(float(action["speed"]), MAX_SPEED)
    if "duration" in action:
        action["duration"] = float(action["duration"])
    return action


def emergency_stop_robot(bridge):
    """Attempt to immediately halt the robot by repeating stop commands."""
    """Send stop command as aggressively as possible."""
    try:
        # Send stop=True 15 times with minimal delay #
        for _ in range(15):
            bridge._publish(x=0.0, y=0.0, yaw_rate=0.0, stop=True)
            time.sleep(0.02)
        # Then call the full stop method
        bridge.stop()
        time.sleep(0.3)
        # One more for good measure
        bridge.stop()
    except Exception as e:
        pass

def stream_command(user_input, dog_id="dog1"):
    """Generator for server-sent events that drives command execution and UI feedback."""
    """Generator that yields SSE events for the UI to consume."""
    cancel_event.clear()
    def event(kind, data):
        return f"data: {json.dumps({'type': kind, **data})}\n\n"

    # Emergency stop bypass
    if user_input.strip().lower() in ("stop", "halt", "emergency stop"):
        yield event("log", {"msg": "⚠ Emergency stop triggered"})
        try:
            bridge = get_bridge(dog_id)
            emergency_stop_robot(bridge)
            yield event("done", {"msg": "Robot stopped."})
        except Exception as e:
            yield event("error", {"msg": str(e)})
        return

    # Reject unrelated inputs that don't mention allowed actions
    lowered = user_input.strip().lower()
    if not any(k in lowered for k in ALLOWED_KEYWORDS):
        yield event("log", {"msg": "Input does not appear to be a robot command."})
        yield event("log", {"msg": "Please enter a valid command from: cautious_walk, sit, stop, turn_left, turn_right, take_picture"})
        yield event("done", {"msg": "No actions executed."})
        return

    # Ask the NIM
    yield event("log", {"msg": "Sending to NIM model..."})
    try:
        raw = send_to_nim(get_prompt(user_input))
    except Exception as e:
        yield event("error", {"msg": f"NIM error: {e}"})
        return

    yield event("log", {"msg": "Model response received"})

    # Parse
    try:
        clean = raw.strip().strip("```json").strip("```").strip()
        intent = json.loads(clean)
        actions = intent.get("actions", [intent])
    except json.JSONDecodeError as e:
        yield event("error", {"msg": f"Could not parse model response: {e}"})
        return

    yield event("plan", {"actions": [a.get("action") for a in actions], "total": len(actions)})

    # Connect to robot
    try:
        bridge = get_bridge(dog_id)
    except Exception as e:
        yield event("error", {"msg": str(e)})
        return

    all_captured_images = []
    CAPTURE_INTERVAL = 2.0

    # Execute each action
    for i, action in enumerate(actions):
        try:
            validate_and_clamp(action)
        except ValueError as e:
            yield event("error", {"msg": str(e)})
            emergency_stop_robot(bridge)
            return

        action_name = action.get("action")
        duration = float(action.get("duration", 3.0))
        speed = float(action.get("speed", 0.10))

        yield event("action_start", {
            "index": i,
            "action": action_name,
            "duration": duration,
            "speed": speed,
            "total": len(actions)
        })

        try:
            if action_name == "cautious_walk":
                SEGMENT = 2.0
                remaining = duration
                elapsed_total = 0.0
                last_capture_at = -CAPTURE_INTERVAL
                elapsed_for_ui = 0.0
                obstacle_hit = False
                TURN_45_DEGREES = 2.25  # calibrated: 90° = 4.5s

                while remaining > 0:
                    this_segment = min(SEGMENT, remaining)

                    # Start walking
                    bridge._publish(x=speed, y=0.0, yaw_rate=0.0, stop=False)
                    steps = int(this_segment * 10)

                    for step in range(steps):
                        # Check LiDAR every 3 steps (every 0.3s) for faster response
                        if step % 3 == 0:
                            dist = bridge.get_lidar_distance()
                            if dist is not None and dist < SAFE_DISTANCE:
                                emergency_stop_robot(bridge)
                                yield event("log", {"msg": f"⚠ LiDAR: obstacle at {dist:.2f}m — avoiding..."})
                        time.sleep(0.1)
                        elapsed_for_ui += 0.1
                        pct = int((elapsed_for_ui / duration) * 100)
                        yield event("progress", {"index": i, "pct": pct, "elapsed": round(elapsed_for_ui, 1)})

                        if cancel_event.is_set():
                            emergency_stop_robot(bridge)
                            yield event("log", {"msg": "⚠ Stop requested — halting robot."})
                            yield event("done", {"msg": "Command stopped."})
                            return

                        # Check LiDAR every 3 steps (every 0.3s) for faster response
                        if step % 3 == 0:
                            dist = bridge.get_lidar_distance()
                            if dist is not None and dist < SAFE_DISTANCE:
                                emergency_stop_robot(bridge)
                                yield event("log", {"msg": f"⚠ LiDAR: obstacle at {dist:.2f}m — avoiding..."})

                                # Try turning right 45°
                                bridge._publish(yaw_rate=-speed, stop=False)
                                time.sleep(TURN_45_DEGREES)
                                bridge.stop()
                                time.sleep(0.3)

                                new_dist = bridge.get_lidar_distance()
                                path_clear = False

                                if new_dist is None or new_dist >= SAFE_DISTANCE:
                                    yield event("log", {"msg": "✓ Turned right 45° — path clear, continuing..."})
                                    path_clear = True
                                else:
                                    # Both turns blocked — back up and turn 180°
                                    yield event("log", {"msg": "⚠ Both directions blocked — backing up..."})

                                    # Return to center heading first (was at 45° left, turn back 45° right)
                                    yield event("log", {"msg": "⚠ Both directions blocked — backing up..."})

                                    # Return to center heading first (was at 45° left, turn back 45° right)
                                    yield event("log", {"msg": "↩ Returning to center heading..."})                                     
                                    bridge._publish(yaw_rate=-speed, stop=False)
                                    time.sleep(TURN_45_DEGREES)
                                    bridge.stop()
                                    time.sleep(0.3)

                                    # Walk backward to create clearance
                                    bridge._publish(x=-speed, y=0.0, yaw_rate=0.0, stop=False)
                                    time.sleep(2.0)
                                    bridge.stop()
                                    time.sleep(0.3)

                                    # Turn a full 180° to face the opposite direction
                                    TURN_180_DEGREES = TURN_45_DEGREES * 4  # 90°=4.5s, so 180°=9.0s
                                    yield event("log", {"msg": "↩ Turning 180°..."})
                                    yield event("log", {"msg": "↩ Turning 180°..."})
                                    bridge._publish(yaw_rate=-speed, stop=False)
                                    time.sleep(TURN_180_DEGREES)
                                    bridge.stop()
                                    time.sleep(0.3)

                                    final_dist = bridge.get_lidar_distance()
                                    if final_dist is None or final_dist >= SAFE_DISTANCE:
                                        yield event("log", {"msg": "✓ Turned around — path clear, continuing in new direction..."})
                                        path_clear = True
                                    else:
                                        yield event("log", {"msg": "⚠ Still blocked after turning around — stopping for new instructions."})
                                        yield event("obstacle", {
                                            "msg": "⚠ Surrounded by obstacles — robot stopped. Please give new instructions.",
                                            "image": ""
                                        })
                                        obstacle_hit = True
                                        break

                                if path_clear:
                                    # Resume walking forward in the new heading
                                    bridge._publish(x=speed, y=0.0, yaw_rate=0.0, stop=False)

                    if obstacle_hit:
                        break

                    # Normal end-of-segment stop
                    bridge.stop()
                    time.sleep(0.3)

                    remaining -= this_segment
                    elapsed_total += this_segment

                    # Capture image if interval reached
                    if round(elapsed_total - last_capture_at, 1) >= CAPTURE_INTERVAL:
                        time.sleep(1.2)
                        try:
                            from datetime import datetime
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            yield event("log", {"msg": f"Capturing image at {round(elapsed_total, 1)}s..."})
                            filepath = bridge.take_picture()
                            all_captured_images.append(filepath)
                            last_capture_at = elapsed_total
                            filename = os.path.basename(filepath)
                            captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            yield event("image", {"src": f"/captures/{filename}", "label": filename, "captured_at": captured_at, "dog_id": dog_id, "waypoint_name": action.get("waypoint_name"), "route_name": action.get("route_name")})
                            yield event("log", {"msg": f"✓ Image saved: {filename}"})
                            yield event("log", {"msg": "✓ Path clear — continuing..."})
                        except Exception as e:
                            yield event("log", {"msg": f"Capture failed: {e}"})

                if obstacle_hit:
                    yield event("done", {"msg": "Robot stopped — surrounded by obstacles. Enter a new command."})
                    return

            elif action_name == "take_picture":
                try:
                    yield event("log", {"msg": "📷 Taking picture..."})
                    filepath = bridge.take_picture()
                    all_captured_images.append(filepath)
                    filename = os.path.basename(filepath)
                    captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    yield event("image", {"src": f"/captures/{filename}", "label": filename, "captured_at": captured_at, "dog_id": dog_id, "waypoint_name": action.get("waypoint_name"), "route_name": action.get("route_name")})
                    yield event("log", {"msg": f"✓ Image saved: {filename}"})
                    yield event("progress", {"index": i, "pct": 100, "elapsed": 0})
                except Exception as e:
                    yield event("error", {"msg": f"Camera failed: {e}"})

            elif action_name == "turn_left":
                bridge._publish(yaw_rate=speed, stop=False)
                steps = int(duration * 10)
                for step in range(steps):
                    time.sleep(0.1)
                    if cancel_event.is_set():
                        emergency_stop_robot(bridge)
                        yield event("log", {"msg": "⚠ Stop requested — halting robot."})
                        yield event("done", {"msg": "Command stopped."})
                        return
                    pct = int(((step + 1) / steps) * 100)
                    yield event("progress", {"index": i, "pct": pct, "elapsed": round((step + 1) * 0.1, 1)})
                bridge.stop()
                time.sleep(0.3)

                if cancel_event.is_set():
                    yield event("log", {"msg": "⚠ Stop requested — halting robot."})
                    yield event("done", {"msg": "Command stopped."})
                    return

                # Capture after turn if duration >= 4 seconds
                if duration >= 4.0:
                    time.sleep(1.2)  # settle before capture
                    try:
                        from datetime import datetime
                        yield event("log", {"msg": "Capturing image after turn..."})
                        filepath = bridge.take_picture()
                        all_captured_images.append(filepath)
                        filename = os.path.basename(filepath)
                        captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        yield event("image", {"src": f"/captures/{filename}", "label": filename, "captured_at": captured_at, "dog_id": dog_id, "waypoint_name": action.get("waypoint_name"), "route_name": action.get("route_name")})
                        yield event("log", {"msg": f"✓ Image saved: {filename}"})
                    except Exception as e:
                        yield event("log", {"msg": f"Capture failed: {e}"})
            elif action_name == "walk_backward":
                bridge._publish(x=-speed, y=0.0, yaw_rate=0.0, stop=False)
                bridge._publish(x=-speed, y=0.0, yaw_rate=0.0, stop=False)  
                steps = int(duration * 10)
                for step in range(steps):
                    time.sleep(0.1)
                    if cancel_event.is_set():
                        emergency_stop_robot(bridge)
                        yield event("log", {"msg": "⚠ Stop requested — halting robot."})
                        yield event("done", {"msg": "Command stopped."})
                        return
                    pct = int(((step + 1) / steps) * 100)
                    yield event("progress", {"index": i, "pct": pct, "elapsed": round((step + 1) * 0.1, 1)})
                bridge.stop()
                time.sleep(0.3)
            elif action_name == "turn_right":
                bridge._publish(yaw_rate=-speed, stop=False)
                steps = int(duration * 10)
                for step in range(steps):
                    time.sleep(0.1)
                    if cancel_event.is_set():
                        emergency_stop_robot(bridge)
                        yield event("log", {"msg": "⚠ Stop requested — halting robot."})
                        yield event("done", {"msg": "Command stopped."})
                        return
                    pct = int(((step + 1) / steps) * 100)
                    yield event("progress", {"index": i, "pct": pct, "elapsed": round((step + 1) * 0.1, 1)})
                bridge.stop()
                time.sleep(0.3)

                if cancel_event.is_set():
                    yield event("log", {"msg": "⚠ Stop requested — halting robot."})
                    yield event("done", {"msg": "Command stopped."})
                    return

                # Capture after turn if duration >= 4 seconds
                if duration >= 4.0:
                    time.sleep(1.2)  # settle before capture
                    try:
                        from datetime import datetime
                        yield event("log", {"msg": "Capturing image after turn..."})
                        filepath = bridge.take_picture()
                        all_captured_images.append(filepath)
                        filename = os.path.basename(filepath)
                        captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        yield event("image", {"src": f"/captures/{filename}", "label": filename, "captured_at": captured_at, "dog_id": dog_id, "waypoint_name": action.get("waypoint_name"), "route_name": action.get("route_name")})
                        yield event("log", {"msg": f"✓ Image saved: {filename}"})
                    except Exception as e:
                        yield event("log", {"msg": f"Capture failed: {e}"})

            elif action_name == "sit":
                bridge.sit()
                yield event("progress", {"index": i, "pct": 100, "elapsed": 0})

            elif action_name == "stop":
                emergency_stop_robot(bridge)
                yield event("progress", {"index": i, "pct": 100, "elapsed": 0})

        except Exception as e:
            yield event("error", {"msg": f"Execution error: {e}"})
            try:
                emergency_stop_robot(bridge)
            except Exception:
                pass
            return
        
        #hey everyone 


        yield event("action_done", {"index": i, "action": action_name})

        yield event("done", {"msg": f"Completed {len(actions)} action(s)."})


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return {"error": "Invalid request body"}, 400
    requested_images = data.get("images")
    if requested_images is None and data.get("filepath"):
        requested_images = [{"filepath": data["filepath"]}]

    if not isinstance(requested_images, list) or not requested_images:
        return {"error": "No images provided"}, 400

    capture_root = os.path.realpath(CAPTURE_DIR)
    images = []
    for image in requested_images:
        if not isinstance(image, dict):
            return {"error": "Each image must be an object"}, 400
        filepath = image.get("filepath", "")
        if not isinstance(filepath, str) or not filepath.strip():
            return {"error": "Each image must include a filepath"}, 400

        resolved_path = os.path.realpath(filepath.strip())
        try:
            is_capture = os.path.commonpath((capture_root, resolved_path)) == capture_root
        except ValueError:
            is_capture = False
        if not is_capture or resolved_path == capture_root:
            return {"error": "Invalid filepath"}, 400

        waypoint_name = image.get("waypoint_name")
        if waypoint_name is not None:
            waypoint_name = str(waypoint_name).strip() or None
        route_name = image.get("route_name")
        if route_name is not None:
            route_name = str(route_name).strip() or None
        images.append({
            "filepath": resolved_path,
            "waypoint_name": waypoint_name,
            "route_name": route_name,
        })

    route_name = str(data.get("route_name") or next(
        (image["route_name"] for image in images if image["route_name"]),
        "Data Center Patrol",
    )).strip() or "Data Center Patrol"

    def generate():
        from vision.compliance_checker import check_compliance_with_nim
        from vision.report_generator import generate_report
        from datetime import datetime

        try:
            all_findings = []
            for image in images:
                filepath = image["filepath"]
                filename = os.path.basename(filepath)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                waypoint_name = image["waypoint_name"]
                location = f"{waypoint_name}: " if waypoint_name else ""
                yield f"data: {json.dumps({'type': 'log', 'msg': f'Analyzing {location}{filename}...'})}\n\n"

                findings = check_compliance_with_nim(filepath=filepath, timestamp=timestamp)
                for finding in findings:
                    finding["waypoint_name"] = waypoint_name
                all_findings.append(findings)

                high_fails = [
                    f for f in findings
                    if f["status"] == "FAIL" and f["severity"] in ("HIGH", "ALERT")
                ]
                other_fails = [
                    f for f in findings
                    if f["status"] == "FAIL" and f["severity"] in ("MEDIUM", "LOW")
                ]
                image_status = "FAIL" if high_fails else "WARNING" if other_fails else "PASS"
                if any(f.get("rule_id") == "PHONE_001" and f["status"] == "FAIL" for f in findings):
                    yield f"data: {json.dumps({'type': 'log', 'msg': f'Lost cellphone detected in {filename}'})}\n\n"

                visible_findings = [
                    {
                        "rule_name": f["rule_name"],
                        "severity": f["severity"],
                        "status": f["status"],
                        "remediation": f["remediation"],
                    }
                    for f in findings
                ]
                yield f"data: {json.dumps({'type': 'image_findings', 'filename': filename, 'waypoint_name': waypoint_name, 'status': image_status, 'findings': visible_findings})}\n\n"

            report, json_path, txt_path = generate_report(
                all_findings=all_findings,
                location="SHI Lab",
                inspector="NemoClaw",
                route_name=route_name,
            )
            total_fails = sum(
                finding["status"] == "FAIL"
                for findings in all_findings
                for finding in findings
            )
            yield f"data: {json.dumps({'type': 'report_summary', 'overall': report['overall_status'], 'total_images': len(images), 'total_fails': total_fails, 'report_file': os.path.basename(txt_path), 'dog_id': data.get('dog_id', 'dog1')})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'msg': 'Analysis complete.'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'msg': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.route("/api/status", methods=["GET"])
def api_status():
    """
    Returns the current system status.

    Used by:
    - Pair & Connect Screen
    - Startup Monitoring
    - Future Route Status Tracking
    """

    return status.get_status()

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/clear-image", methods=["POST"])
def clear_image():
    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()

    if not filename:
        return {"error": "No filename provided"}, 400

    safe_name = os.path.basename(filename)
    if not safe_name or safe_name != filename:
        return {"error": "Invalid filename"}, 400

    target_path = os.path.abspath(os.path.join(CAPTURE_DIR, safe_name))
    if os.path.commonpath([os.path.abspath(CAPTURE_DIR), target_path]) != os.path.abspath(CAPTURE_DIR):
        return {"error": "Invalid filename"}, 400

    if os.path.exists(target_path):
        os.remove(target_path)

    return {"status": "deleted", "filename": safe_name}


@app.route("/captures/<filename>")
def serve_capture(filename):
    return send_from_directory(CAPTURE_DIR, filename)


@app.route("/reports/<filename>")
def serve_report(filename):
    return send_from_directory(REPORT_DIR, filename)

# ---------------------------------------------------------------------------
# Waypoint patrol: runs a saved route (routes/*.json) on the dog's map.
# The dog must be in navigation mode with rosbridge running
# (roslaunch pug_navigation patrol.launch map:=datacenter_01 on the dog).
# ---------------------------------------------------------------------------

ROUTES_DIR = os.path.join(BASE_DIR, "routes")
_patrols = {}              # dog_id -> RouteRunner while a patrol is running
_patrol_lock = threading.Lock()

# Runner statuses that end a patrol, and how the UI should show them
_PATROL_END = {
    "route_completed": "done",
    "route_stopped": "done",
    "route_failed": "error",
}


def _safe_name(text):
    """'Stop 9 (return)' -> 'Stop-9-return' for use in a filename."""
    keep = "".join(c if c.isalnum() else "-" for c in text)
    return "-".join(part for part in keep.split("-") if part)


@app.route("/routes", methods=["GET"])
def list_routes():
    """Route files the UI can offer in the patrol dropdown."""
    from navigation.route_loader import load_route
    routes = []
    for fname in sorted(os.listdir(ROUTES_DIR)):
        if not fname.endswith(".json"):
            continue
        try:
            r = load_route(os.path.join(ROUTES_DIR, fname))
            routes.append({"file": fname, "name": r["route_name"],
                           "stops": len(r["waypoints"])})
        except Exception as e:
            routes.append({"file": fname, "name": fname, "error": str(e)})
    return {"routes": routes}


@app.route("/api/routes", methods=["GET"])
def api_routes():
    """Every route with its waypoints, in the shape the new UI's Route Setup uses."""
    from navigation.route_loader import load_route
    routes = []
    for fname in sorted(os.listdir(ROUTES_DIR)):
        if not fname.endswith(".json"):
            continue
        try:
            r = load_route(os.path.join(ROUTES_DIR, fname))
        except Exception as e:
            routes.append({"file": fname, "name": fname, "error": str(e), "waypoints": []})
            continue
        routes.append({
            "file": fname,
            "name": r["route_name"],
            "waypoints": [{
                "name": wp["name"],
                "x": wp["x"], "y": wp["y"], "yaw": wp["yaw"],
                "photo": wp["action"] == "capture_image",
                "required": wp["required"],
            } for wp in r["waypoints"]],
        })
    return {"routes": routes}


def _dog_status(dog):
    """Card info for one dog: offline / online / ready, plus whether it's patrolling."""
    state, label = dog_prep.dog_status(dog)
    with _patrol_lock:
        on_patrol = dog["id"] in _patrols
    if on_patrol:
        label = "On patrol"
    ids = list(DOG_IPS)
    return {
        "id": dog["id"], "name": dog["name"], "ip": dog["ip"],
        "ssh_user": dog.get("ssh_user", "hiwonder"), "ros_port": dog.get("ros_port", 9090),
        "unit": f"Unit {ids.index(dog['id']) + 1:02d}" if dog["id"] in ids else "Unit --",
        "state": state, "label": label, "online": state != "offline",
        "on_patrol": on_patrol, "battery": None,
    }


@app.route("/api/dogs", methods=["GET"])
def api_dogs():
    """Live status of every configured dog (checked in parallel, ~1 s worst case)."""
    from concurrent.futures import ThreadPoolExecutor
    dogs = reload_dogs()
    if not dogs:
        return {"dogs": []}
    with ThreadPoolExecutor(max_workers=len(dogs)) as pool:
        return {"dogs": list(pool.map(_dog_status, dogs))}


@app.route("/api/dogs", methods=["POST"])
def api_add_dog():
    """Add a dog (from the Add / Remove Dogs dialog)."""
    data = request.get_json(silent=True) or {}
    dog, err = dog_prep.add_dog(data.get("name", ""), data.get("ip", ""),
                                data.get("ssh_user") or "hiwonder", data.get("ros_port", 9090))
    if err:
        return {"error": err}, 400
    reload_dogs()
    return {"dog": dog}


@app.route("/api/dogs/<dog_id>", methods=["DELETE"])
def api_remove_dog(dog_id):
    with _patrol_lock:
        if dog_id in _patrols:
            return {"error": "Stop this dog's patrol before removing it"}, 409
    if not dog_prep.remove_dog(dog_id):
        return {"error": "No such dog"}, 404
    with _bridge_lock:
        _bridges.pop(dog_id, None)
    reload_dogs()
    return {"status": "removed"}


@app.route("/api/dogs/<dog_id>/prepare", methods=["POST"])
def api_prepare_dog(dog_id):
    """Pair & Connect: put the dog in patrol mode over SSH. Streams each step."""
    dog = next((d for d in reload_dogs() if d["id"] == dog_id), None)
    if not dog:
        return {"error": "No such dog"}, 404

    def generate():
        for update in dog_prep.prepare_dog(dog):
            if update.get("done") and update.get("ok"):
                with _bridge_lock:          # drop any stale connection from before
                    _bridges.pop(dog_id, None)
            yield f"data: {json.dumps(update)}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/nim", methods=["GET"])
def api_nim():
    """Is the AI model server (Qwen) answering? Used by the NIM card."""
    models_url = NIM_URL.rsplit("/chat/completions", 1)[0] + "/models"
    try:
        r = http_requests.get(models_url, headers=nim_headers(), timeout=1.5)
        r.raise_for_status()
        ids = [m.get("id") for m in r.json().get("data", [])]
        loaded = NIM_MODEL in ids
        return {"up": True, "model": NIM_MODEL, "loaded": loaded, "available": ids,
                "label": "AI model ready" if loaded else f"Server up, but '{NIM_MODEL}' not loaded"}
    except Exception:
        return {"up": False, "model": NIM_MODEL, "loaded": False, "available": [],
                "label": "AI model offline (start Qwen to analyze photos)"}


@app.route("/api/nim/<action>", methods=["POST"])
def api_nim_control(action):
    """Start or stop the Qwen server kit on this computer (config_nim.yaml: server_dir)."""
    import subprocess
    from nim_config import NIM_SERVER_DIR
    if action not in ("start", "stop"):
        return {"error": "Use start or stop"}, 400
    if not NIM_SERVER_DIR or not os.path.isdir(NIM_SERVER_DIR):
        return {"error": "Set server_dir in config_nim.yaml to the Qwen kit folder"}, 400
    script = os.path.join(NIM_SERVER_DIR, "linux", f"{action}.sh")
    if not os.path.exists(script):
        return {"error": f"{script} not found"}, 400
    args = ["bash", script] + (["--no-harness", "-b"] if action == "start" else [])
    subprocess.Popen(args, cwd=NIM_SERVER_DIR, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return {"status": f"{action} requested"}


@app.route("/new")
def new_ui():
    """The new UI (templates/new_ui.html). The old UI stays at /."""
    return render_template("new_ui.html")


@app.route("/patrol/start", methods=["POST"])
def patrol_start():
    import queue
    from navigation.route_loader import load_route
    from navigation.route_runner import RouteRunner
    from navigation.navigator import RosNavigator

    data = request.get_json(silent=True) or {}
    dog_id = data.get("dog_id", "dog1")
    route_file = os.path.basename(data.get("route", "data_center.json"))
    dog_name = DOG_NAMES.get(dog_id, dog_id)

    with _patrol_lock:
        if dog_id in _patrols:
            return {"error": f"{dog_name} is already on patrol"}, 409

    try:
        route = load_route(os.path.join(ROUTES_DIR, route_file))
    except Exception as e:
        return {"error": f"Could not load route {route_file}: {e}"}, 400

    events = queue.Queue()

    def generate():
        def sse(kind, payload):
            return f"data: {json.dumps({'type': kind, **payload})}\n\n"

        yield sse("log", {"msg": f"Connecting to {dog_name}..."})
        try:
            bridge = get_bridge(dog_id)
            navigator = RosNavigator(bridge.client)
        except Exception as e:
            yield sse("error", {"msg": f"{e}. Is patrol.launch running on the dog?"})
            return

        def capture(waypoint_name):
            path = bridge.take_picture(save_dir=CAPTURE_DIR)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_path = os.path.join(
                CAPTURE_DIR, f"{dog_name}_{_safe_name(waypoint_name)}_{stamp}.jpg")
            os.replace(path, new_path)
            return new_path

        runner = RouteRunner(navigator, dog_name, capture=capture, on_event=events.put)
        with _patrol_lock:
            _patrols[dog_id] = runner

        def run():
            try:
                runner.run(route)
            except Exception as e:
                events.put({"status": "route_failed", "message": str(e),
                            "waypoint": 0, "total": 0, "waypoint_name": None})
            finally:
                try:
                    navigator.close()
                except Exception:
                    pass
                with _patrol_lock:
                    _patrols.pop(dog_id, None)
                events.put(None)  # end of stream

        threading.Thread(target=run, daemon=True).start()

        steps = [wp["name"] for wp in route["waypoints"]]
        yield sse("plan", {"actions": steps, "total": len(steps)})

        while True:
            try:
                e = events.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if e is None:
                break

            st = e.get("status")
            where = f"[{e.get('waypoint')}/{e.get('total')}] {e.get('waypoint_name') or ''}".strip()
            msg = f"{where} {st.replace('_', ' ')}"
            if e.get("message"):
                msg += f": {e['message']}"
            yield sse("log", {"msg": msg})

            idx = (e.get("waypoint") or 1) - 1
            if st == "navigating":
                yield sse("action_start", {"index": idx, "action": e["waypoint_name"],
                                           "total": e.get("total")})
            elif st in ("arrived", "skipped"):
                yield sse("action_done", {"index": idx, "action": e["waypoint_name"]})
            elif st == "captured" and e.get("image"):
                label = os.path.basename(e["image"])
                yield sse("image", {
                    "src": f"/captures/{label}", "label": label,
                    "captured_at": e.get("time", ""), "dog_id": dog_id,
                    "waypoint_name": e.get("waypoint_name"),
                    "route_name": route["route_name"],
                })
            elif st in _PATROL_END:
                yield sse(_PATROL_END[st], {"msg": f"{route['route_name']}: {st.replace('_', ' ')}"})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _stop_patrol(dog_id):
    """Cancel a running patrol for this dog, if any. Returns True if one was running."""
    with _patrol_lock:
        runner = _patrols.get(dog_id)
    if runner:
        runner.stop()
        return True
    return False


@app.route("/patrol/stop", methods=["POST"])
def patrol_stop():
    data = request.get_json(silent=True) or {}
    dog_id = data.get("dog_id", "dog1")
    was_running = _stop_patrol(dog_id)
    try:
        emergency_stop_robot(get_bridge(dog_id))
    except Exception:
        pass
    return {"status": "stopped" if was_running else "not_running"}


@app.route("/cancel", methods=["POST"])
def cancel():
    data = request.get_json(silent=True) or {}
    dog_id = data.get("dog_id", "dog1")
    _stop_patrol(dog_id)  # cancel the navigation goal first, then halt the legs
    try:
        bridge = get_bridge(dog_id)
        emergency_stop_robot(bridge)
    except Exception:
        pass
    cancel_event.set()
    return {"status": "cancelled"}

@app.route("/command", methods=["POST"])
def command():
    data = request.get_json()
    user_input = data.get("input", "").strip()
    dog_id = data.get("dog_id", "dog1")

    if not user_input:
        return {"error": "Empty input"}, 400

    return Response(
        stream_with_context(stream_command(user_input, dog_id)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


if __name__ == "__main__":
    print("NemoClaw UI running at http://localhost:5000")
    app.run(debug=False, threaded=True, port=5000)