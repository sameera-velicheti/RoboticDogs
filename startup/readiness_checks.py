"""
Preflight readiness validation.

All values mocked for now.

Later these will get:
- Battery
- Camera
- LiDAR
- Map
"""

import time


class ReadinessChecks:

    def check_robot(self, dog_name):

        print(f"[CHECKS] Running checks for {dog_name}...")
        time.sleep(1)

        return {
            "battery": True,
            "camera": True,
            "lidar": True,
            "map": True,
            "ready": True
        }