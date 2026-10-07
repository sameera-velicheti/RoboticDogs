"""
Robot readiness checks.

Current version:
- Mock implementation

Future version:
- Battery check
- LiDAR check
- Camera check
- Map check
"""

from status.system_status import status


class ReadinessChecks:

    def check_robot(self, dog_name):

        results = {
            "battery": 87,
            "camera": True,
            "lidar": True,
            "map_loaded": True,
            "emergency_stop_available": True,
            "ready": True
        }

        status.update_dog(
            dog_name,
            **results
        )

        return results