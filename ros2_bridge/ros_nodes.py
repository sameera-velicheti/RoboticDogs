class RosPugBridge:
    """
    Placeholder bridge on laptop side.
    Sends commands instead of executing ROS locally.
    """

    def cautious_walk(self, speed=0.2, duration=1.0, safety_level="medium"):
        print(f"[SEND → ROBOT] cautious_walk speed={speed} duration={duration} safety={safety_level}")

    def sit(self):
        print("[SEND → ROBOT] sit")

    def stop(self):
        print("[SEND → ROBOT] stop")

    def turn_left(self, speed=0.2, duration=1.0):
        print(f"[SEND → ROBOT] turn_left speed={speed} duration={duration}")