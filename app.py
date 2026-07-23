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

app = Flask(__name__)

CAPTURE_DIR = "/home/demo_user/RoboticDogs/captures"
REPORT_DIR = "/home/demo_user/RoboticDogs/reports"
NIM_URL = "http://localhost:8000/v1/chat/completions"
NIM_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

ALLOWED_ACTIONS = {"cautious_walk", "sit", "stop", "turn_left", "turn_right", "take_picture"}
# Build a set of user-facing keywords to match common input variants
ALLOWED_KEYWORDS = set()
for a in ALLOWED_ACTIONS:
    ALLOWED_KEYWORDS.add(a)
    spaced = a.replace("_", " ")
    ALLOWED_KEYWORDS.add(spaced)
    for part in a.split("_"):
        ALLOWED_KEYWORDS.add(part)
MAX_SPEED = 0.15
MAX_DURATION = 60.0
SAFE_DISTANCE = 0.5  # meters — stop if anything within this distance ahead

DOG_IPS = {
    "dog1": "192.168.0.60",
    "dog2": "192.168.0.85",  
    "dog3": "192.168.0.111"  
}

_bridges = {}
_bridge_lock = threading.Lock()
cancel_event = threading.Event()


def get_bridge(dog_id):
    global _bridges
    with _bridge_lock:
        if dog_id not in _bridges or _bridges[dog_id] is None:
            try:
                from ros2_bridge.ros_nodes import RosPugBridge
                ip = DOG_IPS.get(dog_id)
                if not ip:
                    raise ValueError(f"Unknown dog_id: {dog_id}")
                _bridges[dog_id] = RosPugBridge(ip)
            except Exception as e:
                raise RuntimeError(f"Could not connect to {dog_id}: {e}")
        return _bridges[dog_id]
    
def get_prompt(user_instruction):
    return f"""
Return ONLY valid JSON. No explanation, no markdown, no extra text.

Allowed actions: cautious_walk, sit, stop, turn_left, turn_right, take_picture

Rules:
- Always include speed and duration for movement actions
- If given multiple actions, complete one full movement before starting the next
- Default speed is 0.10, default duration is 3.0
- Use the exact duration the user specifies if they mention seconds
- Maximum duration is 60.0, maximum speed is 0.15
- Users should not enter unrelated instructions or questions; only robot movement commands are allowed

Return a list of actions in order:
{{"actions": [
    {{"action": "<action>", "speed": <float>, "duration": <float>}},
    {{"action": "<action>", "speed": <float>, "duration": <float>}}
]}}

User instruction: {user_instruction}
"""


def send_to_nim(prompt):
    payload = {
        "model": NIM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    r = http_requests.post(NIM_URL, json=payload, timeout=30)
    data = r.json()
    return data["choices"][0]["message"]["content"]


def validate_and_clamp(action):
    if action.get("action") not in ALLOWED_ACTIONS:
        raise ValueError(f"Invalid action: {action.get('action')}")
    if "speed" in action:
        action["speed"] = min(float(action["speed"]), MAX_SPEED)
    if "duration" in action:
        action["duration"] = min(float(action["duration"]), MAX_DURATION)
    return action


def emergency_stop_robot(bridge):
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

                while remaining > 0:
                    this_segment = min(SEGMENT, remaining)

                    # Start walking
                    bridge._publish(x=speed, y=0.0, yaw_rate=0.0, stop=False)
                    steps = int(this_segment * 10)

                    for step in range(steps):
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
                                # STOP IMMEDIATELY — aggressive multi-send
                                emergency_stop_robot(bridge)
                                yield event("log", {"msg": f"⚠ LiDAR: obstacle at {dist:.2f}m — STOPPED!"})
                                yield event("obstacle", {
                                    "msg": f"⚠ Obstacle detected at {dist:.2f}m — robot stopped. Please give new instructions.",
                                    "image": ""
                                })
                                obstacle_hit = True
                                break

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
                            yield event("log", {"msg": f"📷 Capturing image at {round(elapsed_total, 1)}s..."})
                            filepath = bridge.take_picture()
                            all_captured_images.append(filepath)
                            last_capture_at = elapsed_total
                            filename = os.path.basename(filepath)
                            captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            yield event("image", {"src": f"/captures/{filename}", "label": filename, "captured_at": captured_at})
                            yield event("log", {"msg": f"✓ Image saved: {filename}"})
                            yield event("log", {"msg": "✓ Path clear — continuing..."})
                        except Exception as e:
                            yield event("log", {"msg": f"Capture failed: {e}"})

                if obstacle_hit:
                    yield event("done", {"msg": "Robot stopped due to obstacle. Enter a new command."})
                    return

            elif action_name == "take_picture":
                try:
                    yield event("log", {"msg": "📷 Taking picture..."})
                    filepath = bridge.take_picture()
                    all_captured_images.append(filepath)
                    filename = os.path.basename(filepath)
                    captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    yield event("image", {"src": f"/captures/{filename}", "label": filename, "captured_at": captured_at})
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
                        yield event("log", {"msg": "📷 Capturing image after turn..."})
                        filepath = bridge.take_picture()
                        all_captured_images.append(filepath)
                        filename = os.path.basename(filepath)
                        captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        yield event("image", {"src": f"/captures/{filename}", "label": filename, "captured_at": captured_at})
                        yield event("log", {"msg": f"✓ Image saved: {filename}"})
                    except Exception as e:
                        yield event("log", {"msg": f"Capture failed: {e}"})

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
                        yield event("log", {"msg": "📷 Capturing image after turn..."})
                        filepath = bridge.take_picture()
                        all_captured_images.append(filepath)
                        filename = os.path.basename(filepath)
                        captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        yield event("image", {"src": f"/captures/{filename}", "label": filename, "captured_at": captured_at})
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
    data = request.get_json()
    filepath = data.get("filepath", "").strip()

    if not filepath:
        return {"error": "No filepath provided"}, 400

    if not filepath.startswith('/home/demo_user/RoboticDogs/captures/'):
        return {"error": "Invalid filepath"}, 400

    def generate():
        from vision.compliance_checker import check_compliance_with_nim
        from vision.report_generator import generate_report
        from datetime import datetime

        filename = os.path.basename(filepath)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        yield f"data: {json.dumps({'type': 'log', 'msg': f'Analyzing {filename}...'})}\n\n"

        try:
            findings = check_compliance_with_nim(
                filepath=filepath,
                timestamp=timestamp
            )

            high_fails = [f for f in findings if f["status"] == "FAIL" and f["severity"] in ("HIGH", "ALERT")]
            medium_low_fails = [f for f in findings if f["status"] == "FAIL" and f["severity"] in ("MEDIUM", "LOW")]

            if high_fails:
                image_status = "FAIL"
            elif medium_low_fails:
                image_status = "WARNING"
            else:
                image_status = "PASS"

            # If a lost cellphone is detected, emit a prominent alert message
            phone_flags = [f for f in findings if f.get('rule_id') == 'PHONE_001' and f.get('status') == 'FAIL']
            if phone_flags:
                yield f"data: {json.dumps({'type': 'log', 'msg': 'Lost cellphone detected'})}\n\n"

            yield f"data: {json.dumps({'type': 'image_findings', 'filename': filename, 'status': image_status, 'findings': [{'rule_name': f['rule_name'], 'severity': f['severity'], 'status': f['status'], 'remediation': f['remediation']} for f in findings]})}\n\n"

            report, json_path, txt_path = generate_report(
                all_findings=[findings],
                location="SHI Lab",
                inspector="NemoClaw"
            )

            total_fails = len(high_fails) + len(medium_low_fails)
            overall = "FAIL" if high_fails else "WARNING" if medium_low_fails else "PASS"

            yield f"data: {json.dumps({'type': 'report_summary', 'overall': overall, 'total_images': 1, 'total_fails': total_fails, 'report_file': os.path.basename(txt_path)})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'msg': 'Analysis complete.'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'msg': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

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

@app.route("/cancel", methods=["POST"])
def cancel():
    data = request.get_json(silent=True) or {}
    dog_id = data.get("dog_id", "dog1")
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

