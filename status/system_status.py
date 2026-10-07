"""
System-wide status tracking

This acts as a single source of truth for:

- Startup progress
- NIM status
- Dog discovery
- Dog readiness
- Route execution

Future UI endpoints will read directly from here.
"""

from copy import deepcopy


class SystemStatus:
    """
    Stores the current state of the entire application.
    """

    def __init__(self):

        self.reset()

    def reset(self):

        self.startup_state = "Offline"

        self.nim = {
            "status": "offline",
            "model": None
        }

        self.dogs = {

            "Pumbaa": {
                "discovered": False,
                "connected": False,
                "services_running": False,
                "battery": None,
                "camera": False,
                "lidar": False,
                "map_loaded": False,
                "emergency_stop_available": False,
                "ready": False,

                # Route tracking
                "route_running": False,
                "route_complete": False,
                "current_waypoint": None
            },

            "Timon": {
                "discovered": False,
                "connected": False,
                "services_running": False,
                "battery": None,
                "camera": False,
                "lidar": False,
                "map_loaded": False,
                "emergency_stop_available": False,
                "ready": False,

                # Route tracking
                "route_running": False,
                "route_complete": False,
                "current_waypoint": None
            }
        }

    # -----------------------------
    # Startup State
    # -----------------------------

    def set_startup_state(self, state):

        self.startup_state = state

    # -----------------------------
    # NIM Updates
    # -----------------------------

    def update_nim_status(
        self,
        status,
        model=None
    ):

        self.nim["status"] = status
        self.nim["model"] = model

    # -----------------------------
    # Dog Updates
    # -----------------------------

    def update_dog(self, dog_name, **kwargs):

        if dog_name not in self.dogs:
            return

        self.dogs[dog_name].update(kwargs)

    # -----------------------------
    # Route Updates
    # -----------------------------

    def start_route(self, dog_name):

        if dog_name not in self.dogs:
            return

        self.dogs[dog_name]["route_running"] = True
        self.dogs[dog_name]["route_complete"] = False

    def complete_route(self, dog_name):

        if dog_name not in self.dogs:
            return

        self.dogs[dog_name]["route_running"] = False
        self.dogs[dog_name]["route_complete"] = True

    def stop_route(self, dog_name):

        if dog_name not in self.dogs:
            return

        self.dogs[dog_name]["route_running"] = False

    def update_waypoint(
        self,
        dog_name,
        waypoint_name
    ):

        if dog_name not in self.dogs:
            return

        self.dogs[dog_name]["current_waypoint"] = waypoint_name

    # -----------------------------
    # Status Retrieval
    # -----------------------------

    def get_status(self):

        return {
            "startup_state": self.startup_state,
            "nim": deepcopy(self.nim),
            "dogs": deepcopy(self.dogs)
        }


# Global shared object

status = SystemStatus()


if __name__ == "__main__":

    print(status.get_status())