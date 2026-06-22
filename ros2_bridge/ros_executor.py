from ros2_bridge.ros_nodes import RosPugBridge

bridge = RosPugBridge()


def execute_command(command: dict):
    action = command.get("action")

    if action == "cautious_walk":
        bridge.cautious_walk(
            speed=command.get("speed", 0.2),
            duration=command.get("duration", 1.0),
            safety_level=command.get("safety_level", "medium")
        )
    else:
        print(f"[WARN] Unknown action: {action}")