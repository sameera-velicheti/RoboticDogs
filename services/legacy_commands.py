"""
Legacy Phase 1 command system for Agentic Paw Patrol.

This preserves the original natural-language movement workflow:

User instruction
    ↓
Qwen / NIM
    ↓
JSON actions
    ↓
Validation
    ↓
ROS commands
    ↓
Robot movement

Phase 2 primarily uses saved waypoint routes, but this remains available
for direct movement / emergency commands.
"""

import json
import os
import time
from datetime import datetime

import requests as http_requests

from nim_config import (
    NIM_MODEL,
    NIM_URL,
    extract_answer,
    extra_params,
    headers as nim_headers,
)

from runtime import (
    cancel_event,
    emergency_stop_robot,
    get_bridge,
)


ALLOWED_ACTIONS = {
    "cautious_walk",
    "walk_backward",
    "sit",
    "stop",
    "turn_left",
    "turn_right",
    "take_picture",
}

# Build a set of user-facing keywords to match common input variants.
ALLOWED_KEYWORDS = set()

for action in ALLOWED_ACTIONS:
    ALLOWED_KEYWORDS.add(action)

    spaced = action.replace("_", " ")
    ALLOWED_KEYWORDS.add(spaced)

    for part in action.split("_"):
        ALLOWED_KEYWORDS.add(part)


MAX_SPEED = 0.15

# Stop if anything is within this distance ahead.
SAFE_DISTANCE = 0.5


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
    """Send a prompt to the configured AI model and return its answer."""

    payload = {
        "model": NIM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.2,
        **extra_params(),
    }

    response = http_requests.post(
        NIM_URL,
        json=payload,
        headers=nim_headers(),
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    return extract_answer(
        data["choices"][0]["message"]
    )


def validate_and_clamp(action):
    """Validate the model action and clamp numeric values to safety limits."""

    if action.get("action") not in ALLOWED_ACTIONS:
        raise ValueError(
            f"Invalid action: {action.get('action')}"
        )

    if "speed" in action:
        action["speed"] = min(
            float(action["speed"]),
            MAX_SPEED,
        )

    if "duration" in action:
        action["duration"] = float(
            action["duration"]
        )

    return action


def stream_command(user_input, dog_id="dog1"):
    """
    Generator that executes Phase 1 commands and yields server-sent events
    for the UI.
    """

    cancel_event.clear()

    def event(kind, data):
        return (
            f"data: "
            f"{json.dumps({'type': kind, **data})}"
            f"\n\n"
        )

    # Emergency stop bypass.
    if user_input.strip().lower() in (
        "stop",
        "halt",
        "emergency stop",
    ):
        yield event(
            "log",
            {
                "msg": "⚠ Emergency stop triggered"
            },
        )

        try:
            bridge = get_bridge(dog_id)
            emergency_stop_robot(bridge)

            yield event(
                "done",
                {
                    "msg": "Robot stopped."
                },
            )

        except Exception as error:
            yield event(
                "error",
                {
                    "msg": str(error)
                },
            )

        return

    # Reject unrelated inputs that do not mention allowed actions.
    lowered = user_input.strip().lower()

    if not any(
        keyword in lowered
        for keyword in ALLOWED_KEYWORDS
    ):
        yield event(
            "log",
            {
                "msg":
                    "Input does not appear to be a robot command."
            },
        )

        yield event(
            "log",
            {
                "msg":
                    "Please enter a valid command from: "
                    "cautious_walk, sit, stop, turn_left, "
                    "turn_right, take_picture"
            },
        )

        yield event(
            "done",
            {
                "msg": "No actions executed."
            },
        )

        return

    # Ask the AI model.
    yield event(
        "log",
        {
            "msg": "Sending to NIM model..."
        },
    )

    try:
        raw = send_to_nim(
            get_prompt(user_input)
        )

    except Exception as error:
        yield event(
            "error",
            {
                "msg": f"NIM error: {error}"
            },
        )
        return

    yield event(
        "log",
        {
            "msg": "Model response received"
        },
    )

    # Parse the AI response.
    try:
        clean = (
            raw.strip()
            .strip("```json")
            .strip("```")
            .strip()
        )

        intent = json.loads(clean)
        actions = intent.get(
            "actions",
            [intent],
        )

    except json.JSONDecodeError as error:
        yield event(
            "error",
            {
                "msg":
                    f"Could not parse model response: {error}"
            },
        )
        return

    yield event(
        "plan",
        {
            "actions": [
                action.get("action")
                for action in actions
            ],
            "total": len(actions),
        },
    )

    # Connect to the selected dog.
    try:
        bridge = get_bridge(dog_id)

    except Exception as error:
        yield event(
            "error",
            {
                "msg": str(error)
            },
        )
        return

    all_captured_images = []
    capture_interval = 2.0

    # Execute each action.
    for i, action in enumerate(actions):

        try:
            validate_and_clamp(action)

        except ValueError as error:
            yield event(
                "error",
                {
                    "msg": str(error)
                },
            )

            emergency_stop_robot(bridge)
            return

        action_name = action.get("action")
        duration = float(
            action.get("duration", 3.0)
        )
        speed = float(
            action.get("speed", 0.10)
        )

        yield event(
            "action_start",
            {
                "index": i,
                "action": action_name,
                "duration": duration,
                "speed": speed,
                "total": len(actions),
            },
        )

        try:

            # ---------------------------------------------------------------
            # Cautious walk
            # ---------------------------------------------------------------

            if action_name == "cautious_walk":

                segment = 2.0
                remaining = duration
                elapsed_total = 0.0
                last_capture_at = -capture_interval
                elapsed_for_ui = 0.0
                obstacle_hit = False

                # Calibrated: 90° = 4.5 seconds.
                turn_45_degrees = 2.25

                while remaining > 0:

                    this_segment = min(
                        segment,
                        remaining,
                    )

                    # Start walking.
                    bridge._publish(
                        x=speed,
                        y=0.0,
                        yaw_rate=0.0,
                        stop=False,
                    )

                    steps = int(
                        this_segment * 10
                    )

                    for step in range(steps):

                        time.sleep(0.1)
                        elapsed_for_ui += 0.1

                        percent = int(
                            (elapsed_for_ui / duration)
                            * 100
                        )

                        yield event(
                            "progress",
                            {
                                "index": i,
                                "pct": percent,
                                "elapsed": round(
                                    elapsed_for_ui,
                                    1,
                                ),
                            },
                        )

                        if cancel_event.is_set():

                            emergency_stop_robot(
                                bridge
                            )

                            yield event(
                                "log",
                                {
                                    "msg":
                                        "⚠ Stop requested — "
                                        "halting robot."
                                },
                            )

                            yield event(
                                "done",
                                {
                                    "msg":
                                        "Command stopped."
                                },
                            )

                            return

                        # Check LiDAR every ~0.3 seconds.
                        if step % 3 == 0:

                            distance = (
                                bridge
                                .get_lidar_distance()
                            )

                            if (
                                distance is not None
                                and distance < SAFE_DISTANCE
                            ):

                                emergency_stop_robot(
                                    bridge
                                )

                                yield event(
                                    "log",
                                    {
                                        "msg":
                                            "⚠ LiDAR: obstacle at "
                                            f"{distance:.2f}m — "
                                            "avoiding..."
                                    },
                                )

                                # Try turning right 45°.
                                bridge._publish(
                                    yaw_rate=-speed,
                                    stop=False,
                                )

                                time.sleep(
                                    turn_45_degrees
                                )

                                bridge.stop()
                                time.sleep(0.3)

                                new_distance = (
                                    bridge
                                    .get_lidar_distance()
                                )

                                path_clear = False

                                if (
                                    new_distance is None
                                    or new_distance
                                    >= SAFE_DISTANCE
                                ):

                                    yield event(
                                        "log",
                                        {
                                            "msg":
                                                "✓ Turned right "
                                                "45° — path clear, "
                                                "continuing..."
                                        },
                                    )

                                    path_clear = True

                                else:

                                    # Back up and turn around.
                                    yield event(
                                        "log",
                                        {
                                            "msg":
                                                "⚠ Direction blocked "
                                                "— backing up..."
                                        },
                                    )

                                    bridge._publish(
                                        yaw_rate=-speed,
                                        stop=False,
                                    )

                                    time.sleep(
                                        turn_45_degrees
                                    )

                                    bridge.stop()
                                    time.sleep(0.3)

                                    bridge._publish(
                                        x=-speed,
                                        y=0.0,
                                        yaw_rate=0.0,
                                        stop=False,
                                    )

                                    time.sleep(2.0)

                                    bridge.stop()
                                    time.sleep(0.3)

                                    turn_180_degrees = (
                                        turn_45_degrees
                                        * 4
                                    )

                                    yield event(
                                        "log",
                                        {
                                            "msg":
                                                "↩ Turning 180°..."
                                        },
                                    )

                                    bridge._publish(
                                        yaw_rate=-speed,
                                        stop=False,
                                    )

                                    time.sleep(
                                        turn_180_degrees
                                    )

                                    bridge.stop()
                                    time.sleep(0.3)

                                    final_distance = (
                                        bridge
                                        .get_lidar_distance()
                                    )

                                    if (
                                        final_distance is None
                                        or final_distance
                                        >= SAFE_DISTANCE
                                    ):

                                        yield event(
                                            "log",
                                            {
                                                "msg":
                                                    "✓ Turned around "
                                                    "— path clear, "
                                                    "continuing..."
                                            },
                                        )

                                        path_clear = True

                                    else:

                                        yield event(
                                            "obstacle",
                                            {
                                                "msg":
                                                    "⚠ Surrounded by "
                                                    "obstacles — robot "
                                                    "stopped. Please "
                                                    "give new "
                                                    "instructions.",
                                                "image": "",
                                            },
                                        )

                                        obstacle_hit = True
                                        break

                                if path_clear:

                                    bridge._publish(
                                        x=speed,
                                        y=0.0,
                                        yaw_rate=0.0,
                                        stop=False,
                                    )

                    if obstacle_hit:
                        break

                    bridge.stop()
                    time.sleep(0.3)

                    remaining -= this_segment
                    elapsed_total += this_segment

                    # Capture image if interval reached.
                    if (
                        round(
                            elapsed_total
                            - last_capture_at,
                            1,
                        )
                        >= capture_interval
                    ):

                        time.sleep(1.2)

                        try:
                            yield event(
                                "log",
                                {
                                    "msg":
                                        "Capturing image at "
                                        f"{round(elapsed_total, 1)}s..."
                                },
                            )

                            filepath = (
                                bridge.take_picture()
                            )

                            all_captured_images.append(
                                filepath
                            )

                            last_capture_at = (
                                elapsed_total
                            )

                            filename = (
                                os.path.basename(
                                    filepath
                                )
                            )

                            captured_at = (
                                datetime.now()
                                .strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                )
                            )

                            yield event(
                                "image",
                                {
                                    "src":
                                        f"/captures/{filename}",
                                    "label":
                                        filename,
                                    "captured_at":
                                        captured_at,
                                    "dog_id":
                                        dog_id,
                                    "waypoint_name":
                                        action.get(
                                            "waypoint_name"
                                        ),
                                    "route_name":
                                        action.get(
                                            "route_name"
                                        ),
                                },
                            )

                            yield event(
                                "log",
                                {
                                    "msg":
                                        f"✓ Image saved: "
                                        f"{filename}"
                                },
                            )

                        except Exception as error:
                            yield event(
                                "log",
                                {
                                    "msg":
                                        f"Capture failed: "
                                        f"{error}"
                                },
                            )

                if obstacle_hit:

                    yield event(
                        "done",
                        {
                            "msg":
                                "Robot stopped — "
                                "surrounded by obstacles. "
                                "Enter a new command."
                        },
                    )

                    return

            # ---------------------------------------------------------------
            # Take picture
            # ---------------------------------------------------------------

            elif action_name == "take_picture":

                try:
                    yield event(
                        "log",
                        {
                            "msg":
                                "📷 Taking picture..."
                        },
                    )

                    filepath = (
                        bridge.take_picture()
                    )

                    all_captured_images.append(
                        filepath
                    )

                    filename = os.path.basename(
                        filepath
                    )

                    captured_at = (
                        datetime.now()
                        .strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    )

                    yield event(
                        "image",
                        {
                            "src":
                                f"/captures/{filename}",
                            "label":
                                filename,
                            "captured_at":
                                captured_at,
                            "dog_id":
                                dog_id,
                            "waypoint_name":
                                action.get(
                                    "waypoint_name"
                                ),
                            "route_name":
                                action.get(
                                    "route_name"
                                ),
                        },
                    )

                    yield event(
                        "log",
                        {
                            "msg":
                                f"✓ Image saved: "
                                f"{filename}"
                        },
                    )

                    yield event(
                        "progress",
                        {
                            "index": i,
                            "pct": 100,
                            "elapsed": 0,
                        },
                    )

                except Exception as error:

                    yield event(
                        "error",
                        {
                            "msg":
                                f"Camera failed: "
                                f"{error}"
                        },
                    )

            # ---------------------------------------------------------------
            # Turn left
            # ---------------------------------------------------------------

            elif action_name == "turn_left":

                bridge._publish(
                    yaw_rate=speed,
                    stop=False,
                )

                yield from _timed_motion(
                    bridge=bridge,
                    index=i,
                    duration=duration,
                    event=event,
                )

                # Capture after a longer turn.
                if duration >= 4.0:
                    yield from _capture_after_turn(
                        bridge=bridge,
                        index=i,
                        dog_id=dog_id,
                        action=action,
                        event=event,
                        captured_images=
                            all_captured_images,
                    )

            # ---------------------------------------------------------------
            # Walk backward
            # ---------------------------------------------------------------

            elif action_name == "walk_backward":

                bridge._publish(
                    x=-speed,
                    y=0.0,
                    yaw_rate=0.0,
                    stop=False,
                )

                yield from _timed_motion(
                    bridge=bridge,
                    index=i,
                    duration=duration,
                    event=event,
                )

            # ---------------------------------------------------------------
            # Turn right
            # ---------------------------------------------------------------

            elif action_name == "turn_right":

                bridge._publish(
                    yaw_rate=-speed,
                    stop=False,
                )

                yield from _timed_motion(
                    bridge=bridge,
                    index=i,
                    duration=duration,
                    event=event,
                )

                # Capture after a longer turn.
                if duration >= 4.0:
                    yield from _capture_after_turn(
                        bridge=bridge,
                        index=i,
                        dog_id=dog_id,
                        action=action,
                        event=event,
                        captured_images=
                            all_captured_images,
                    )

            # ---------------------------------------------------------------
            # Sit
            # ---------------------------------------------------------------

            elif action_name == "sit":

                bridge.sit()

                yield event(
                    "progress",
                    {
                        "index": i,
                        "pct": 100,
                        "elapsed": 0,
                    },
                )

            # ---------------------------------------------------------------
            # Stop
            # ---------------------------------------------------------------

            elif action_name == "stop":

                emergency_stop_robot(
                    bridge
                )

                yield event(
                    "progress",
                    {
                        "index": i,
                        "pct": 100,
                        "elapsed": 0,
                    },
                )

        except Exception as error:

            yield event(
                "error",
                {
                    "msg":
                        f"Execution error: "
                        f"{error}"
                },
            )

            try:
                emergency_stop_robot(
                    bridge
                )
            except Exception:
                pass

            return

        yield event(
            "action_done",
            {
                "index": i,
                "action": action_name,
            },
        )

    yield event(
        "done",
        {
            "msg":
                f"Completed "
                f"{len(actions)} action(s)."
        },
    )


def _timed_motion(
    bridge,
    index,
    duration,
    event,
):
    """
    Handle duration/progress/cancellation for simple timed movement.
    """

    steps = int(
        duration * 10
    )

    for step in range(steps):

        time.sleep(0.1)

        if cancel_event.is_set():

            emergency_stop_robot(
                bridge
            )

            yield event(
                "log",
                {
                    "msg":
                        "⚠ Stop requested — "
                        "halting robot."
                },
            )

            yield event(
                "done",
                {
                    "msg":
                        "Command stopped."
                },
            )

            return

        percent = int(
            ((step + 1) / steps)
            * 100
        )

        yield event(
            "progress",
            {
                "index": index,
                "pct": percent,
                "elapsed": round(
                    (step + 1) * 0.1,
                    1,
                ),
            },
        )

    bridge.stop()
    time.sleep(0.3)


def _capture_after_turn(
    bridge,
    index,
    dog_id,
    action,
    event,
    captured_images,
):
    """
    Capture an image after a longer turn.
    """

    time.sleep(1.2)

    try:
        yield event(
            "log",
            {
                "msg":
                    "Capturing image "
                    "after turn..."
            },
        )

        filepath = bridge.take_picture()

        captured_images.append(
            filepath
        )

        filename = os.path.basename(
            filepath
        )

        captured_at = (
            datetime.now()
            .strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        yield event(
            "image",
            {
                "src":
                    f"/captures/{filename}",
                "label":
                    filename,
                "captured_at":
                    captured_at,
                "dog_id":
                    dog_id,
                "waypoint_name":
                    action.get(
                        "waypoint_name"
                    ),
                "route_name":
                    action.get(
                        "route_name"
                    ),
            },
        )

        yield event(
            "log",
            {
                "msg":
                    f"✓ Image saved: "
                    f"{filename}"
            },
        )

    except Exception as error:

        yield event(
            "log",
            {
                "msg":
                    f"Capture failed: "
                    f"{error}"
            },
        )