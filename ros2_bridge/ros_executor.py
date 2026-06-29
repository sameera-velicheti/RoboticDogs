from ros2_bridge.ros_nodes import RosPugBridge


def execute_command(command: dict, bridge=None):
    if bridge is None:
        bridge = RosPugBridge()

    action = command.get("action")

    if action == "cautious_walk":
        bridge.cautious_walk(
            speed=command.get("speed", 0.115),
            duration=command.get("duration", 3.0),
            safety_level=command.get("safety_level", "high"),
        )
    elif action == "sit":
        bridge.sit(height=command.get("height", 0.05))
    elif action == "stop":
        bridge.stop()
    elif action == "turn_left":
        bridge.turn_left(
            speed=command.get("speed", 0.15),
            duration=command.get("duration", 2.0),
        )
    elif action == "turn_right":
        bridge.turn_right(
            speed=command.get("speed", 0.15),
            duration=command.get("duration", 2.0),
        )
    else:
        raise ValueError(f"Unknown ROS action: {action}")