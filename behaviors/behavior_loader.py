import json
import os

BEHAVIOR_DIR = os.path.dirname(__file__)


def load_behavior(action: str) -> dict:
    """
    Loads a behavior JSON file from /behaviors based on action name.
    Example: cautious_walk → cautious_walk.json
    """

    file_path = os.path.join(BEHAVIOR_DIR, f"{action}.json")

    if not os.path.exists(file_path):
        raise ValueError(f"Behavior not found: {action}")

    with open(file_path, "r") as f:
        behavior = json.load(f)

    # attach action for traceability
    behavior["action"] = action

    return behavior