"""
NemoClaw UI - Flask backend
Drop this into your RoboticDogs/ root folder and run:
    pip install flask
    python3 app.py
Then open http://localhost:5000 in your browser.
"""

from flask import Flask, render_template, request, Response, stream_with_context
import json
import time
import queue
import threading
import requests as http_requests

app = Flask(__name__)

NIM_URL = "http://localhost:8000/v1/chat/completions"
NIM_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

ALLOWED_ACTIONS = {"cautious_walk", "sit", "stop", "turn_left", "turn_right"}
MAX_SPEED = 0.15
MAX_DURATION = 10.0

# Global bridge — one connection, reused across commands
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

Allowed actions: cautious_walk, sit, stop, turn_left, turn_right

Rules:
- Always include speed and duration for movement actions
- If given multiple actions, complete one full movement before starting the next
- Default speed is 0.10, default duration is 3.0
- Use the exact duration the user specifies if they mention seconds
- Maximum duration is 60.0, maximum speed is 0.20
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


def stream_command(user_input):
    """Generator that yields SSE events for the UI to consume."""

    def event(kind, data):
        return f"data: {json.dumps({'type': kind, **data})}\n\n"

    # Emergency stop bypass
    if user_input.strip().lower() in ("stop", "halt", "emergency stop"):
        yield event("log", {"msg": "⚠ Emergency stop triggered"})
        try:
            bridge = get_bridge()
            bridge.stop()
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

    yield event("log", {"msg": f"Model response received"})

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

    # Execute each action
    for i, action in enumerate(actions):
        try:
            validate_and_clamp(action)
        except ValueError as e:
            yield event("error", {"msg": str(e)})
            bridge.stop()
            return

        action_name = action.get("action")
        duration = action.get("duration", 0)
        speed = action.get("speed", 0)

        yield event("action_start", {
            "index": i,
            "action": action_name,
            "duration": duration,
            "speed": speed,
            "total": len(actions)
        })

        # Execute with progress ticks
        try:
            if action_name == "cautious_walk":
                bridge._publish(x=speed, stop=False)
                steps = int(duration * 10)
                for step in range(steps):
                    time.sleep(0.1)
                    pct = int(((step + 1) / steps) * 100)
                    yield event("progress", {"index": i, "pct": pct, "elapsed": round((step + 1) * 0.1, 1)})
                bridge.stop()

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
                bridge.stop()
                yield event("progress", {"index": i, "pct": 100, "elapsed": 0})

        except Exception as e:
            yield event("error", {"msg": f"Execution error: {e}"})
            try:
                bridge.stop()
            except Exception:
                pass
            return

        yield event("action_done", {"index": i, "action": action_name})

    yield event("done", {"msg": f"Completed {len(actions)} action(s)."})


@app.route("/")
def index():
    return render_template("index.html")


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