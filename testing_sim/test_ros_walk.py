from ros2_bridge.ros_nodes import RosPugBridge

def main():
    print("TEST STARTED")

    node = RosPugBridge()

    node.cautious_walk(speed=0.1, duration=3.0)

    print("TEST COMPLETE")


if __name__ == "__main__":
    main()