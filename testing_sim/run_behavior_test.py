"""Runs a sample robot behavior sequence for local integration testing.
"""

from behaviors.behavior_loader import load_behavior
from ros2_bridge.ros_executor import execute_command

def run():
    """Execute a short sequence of sample behavior commands for test validation."""
    behaviors = [
        "cautious_walk.json",
        "stop.json"
    ]

    for b in behaviors:
        print(f"\n[LOADING] {b}")

        command = load_behavior(b)

        print("[VALIDATED COMMAND]")
        print(command)

        execute_command(command)

if __name__ == "__main__":
    run()