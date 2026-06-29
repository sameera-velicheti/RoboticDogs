from ros2_bridge.ros_nodes import RosPugBridge


def execute_command(command: dict):
    bridge = RosPugBridge()
    
    action = command.get("action")

    if action == "cautious_walk":
        bridge.cautious_walk(
            speed=command.get("speed"),
            duration=command.get("duration"),
            safety_level=command.get("safety_level"),
        )

    elif action == "sit":
        bridge.sit()

    elif action == "stop":
        bridge.stop()

    elif action == "turn_left":
        bridge.turn_left(
            speed=command.get("speed", 0.2),
            duration=command.get("duration", 1.0),
        )

    else:
        raise ValueError(f"Unknown ROS action: {action}")

    bridge.close()