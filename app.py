"""
NemoClaw UI - Flask backend
Drop this into your RoboticDogs/ root folder and run:
    pip install flask
    python3 app.py
Then open http://localhost:5000 in your browser.
"""

import os
from flask import Flask, render_template, request, Response, stream_with_context, send_from_directory
import json
import time
import threading
import requests as http_requests

app = Flask(__name__)

NIM_URL = "http://localhost:8000/v1/chat/completions"
NIM_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

ALLOWED_ACTIONS = {"cautious_walk", "sit", "stop", "turn_left", "turn_right", "take_picture"}
MAX_SPEED = 0.15
MAX_DURATION = 60.0
SAFE_DISTANCE = 0.5  # meters — stop if anything within this distance ahead

_bridge = None
_bridge_lock = threading.Lock()


def get_bridge():
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            try:
                from ros2_bridge.ros_nodes import RosPugBridge
                _bridge = RosPugBridge()
            except Exception as e:
                raise RuntimeError(f"Could not connect to robot: {e}")
        return _bridge


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
        # Send stop=True 15 times with minimal delay
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


def stream_command(user_input):
    """Generator that yields SSE events for the UI to consume."""

    def event(kind, data):
        return f"data: {json.dumps({'type': kind, **data})}\n\n"

    # Emergency stop bypass
    if user_input.strip().lower() in ("stop", "halt", "emergency stop"):
        yield event("log", {"msg": "⚠ Emergency stop triggered"})
        try:
            bridge = get_bridge()
            emergency_stop_robot(bridge)
            yield event("done", {"msg": "Robot stopped."})
        except Exception as e:
            yield event("error", {"msg": str(e)})
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
        bridge = get_bridge()
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
                            yield event("image", {"src": f"/captures/{filename}", "label": filename})
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
                    yield event("image", {"src": f"/captures/{filename}", "label": filename})
                    yield event("log", {"msg": f"✓ Image saved: {filename}"})
                    yield event("progress", {"index": i, "pct": 100, "elapsed": 0})
                except Exception as e:
                    yield event("error", {"msg": f"Camera failed: {e}"})

            elif action_name == "turn_left":
                bridge._publish(yaw_rate=speed, stop=False)
                steps = int(duration * 10)
                for step in range(steps):
                    time.sleep(0.1)
                    pct = int(((step + 1) / steps) * 100)
                    yield event("progress", {"index": i, "pct": pct, "elapsed": round((step + 1) * 0.1, 1)})
                bridge.stop()

            elif action_name == "turn_right":
                bridge._publish(yaw_rate=-speed, stop=False)
                steps = int(duration * 10)
                for step in range(steps):
                    time.sleep(0.1)
                    pct = int(((step + 1) / steps) * 100)
                    yield event("progress", {"index": i, "pct": pct, "elapsed": round((step + 1) * 0.1, 1)})
                bridge.stop()

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

        yield event("action_done", {"index": i, "action": action_name})

    # After ALL actions complete — run full compliance on all captured images
    if all_captured_images:
        yield event("log", {"msg": f"📄 Running final compliance check on all {len(all_captured_images)} image(s)..."})

        from vision.compliance_checker import check_compliance_with_nim
        from vision.report_generator import generate_report
        from datetime import datetime

        all_findings = []
        for img_path in all_captured_images:
            filename = os.path.basename(img_path)
            yield event("log", {"msg": f"Checking: {filename}"})
            findings = check_compliance_with_nim(
                filepath=img_path,
                timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
            )
            all_findings.append(findings)

            fails = [f for f in findings if f["status"] == "FAIL"]
            yield event("image_findings", {
                "filename": filename,
                "status": "FAIL" if fails else "PASS",
                "findings": [
                    {
                        "rule_name": f["rule_name"],
                        "severity": f["severity"],
                        "status": f["status"],
                        "remediation": f["remediation"]
                    }
                    for f in findings
                ]
            })

        report, json_path, txt_path = generate_report(
            all_findings=all_findings,
            location="SHI Lab",
            inspector="NemoClaw"
        )

        total_fails = sum(1 for findings in all_findings for f in findings if f["status"] == "FAIL")
        yield event("report_summary", {
            "overall": "FAIL" if total_fails > 0 else "PASS",
            "total_images": len(all_captured_images),
            "total_fails": total_fails,
            "report_file": os.path.basename(txt_path)
        })

    yield event("done", {"msg": f"Completed {len(actions)} action(s)."})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/captures/<filename>")
def serve_capture(filename):
    return send_from_directory('/home/demo_user/RoboticDogs/captures', filename)


@app.route("/reports/<filename>")
def serve_report(filename):
    return send_from_directory('/home/demo_user/RoboticDogs/reports', filename)


@app.route("/command", methods=["POST"])
def command():
    data = request.get_json()
    user_input = data.get("input", "").strip()
    if not user_input:
        return {"error": "Empty input"}, 400

    return Response(
        stream_with_context(stream_command(user_input)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


if __name__ == "__main__":
    print("NemoClaw UI running at http://localhost:5000")
    app.run(debug=False, threaded=True, port=5000)