ALLOWED_ACTIONS = {"cautious_walk", "sit", "stop", "turn_left"}


def validate_intent(command: dict):
    if "action" not in command:
        raise ValueError("Missing action")

    if command["action"] not in ALLOWED_ACTIONS:
        raise ValueError(f"Invalid action: {command['action']}")

    return True