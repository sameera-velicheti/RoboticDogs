import logging

logger = logging.getLogger(__name__)

ALLOWED_ACTIONS = {"cautious_walk", "sit", "stop", "turn_left", "turn_right"}

# Safe limits based on your lab testing
MAX_SPEED = 0.20        # reduced from 0.25 since dog is falling
MAX_DURATION = 60.0     # max 60 seconds per command
MIN_SPEED = 0.05


def validate_intent(command: dict) -> bool:
    if not isinstance(command, dict):
        raise ValueError("Command must be a JSON object")

    if "action" not in command:
        raise ValueError("Missing action field")

    if command["action"] not in ALLOWED_ACTIONS:
        raise ValueError(f"Invalid action: {command['action']}. Allowed: {ALLOWED_ACTIONS}")

    # Clamp speed if present
    if "speed" in command:
        speed = float(command["speed"])
        if speed > MAX_SPEED:
            logger.warning(f"Speed {speed} exceeded max, clamping to {MAX_SPEED}")
            command["speed"] = MAX_SPEED
        if speed < MIN_SPEED and command["action"] not in ("sit", "stop"):
            command["speed"] = MIN_SPEED

    # Clamp duration if present
    if "duration" in command:
        duration = float(command["duration"])
        if duration > MAX_DURATION:
            logger.warning(f"Duration {duration} exceeded max, clamping to {MAX_DURATION}")
            command["duration"] = MAX_DURATION

    return True