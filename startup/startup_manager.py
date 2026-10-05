"""
Main startup flow.

Application Startup

Check NIM
↓
Connect SSH
↓
Launch Services
↓
Discover Dogs
↓
Verify Status
↓
Ready
"""

from enum import Enum

from nim_manager import NIMManager
from ssh_manager import SSHManager
from discovery_manager import DiscoveryManager
from readiness_checks import ReadinessChecks


class StartupState(Enum):

    STARTING_NIM = "Starting NIM"
    CONNECTING_SSH = "Connecting SSH"
    LAUNCHING_SERVICES = "Launching Services"
    DISCOVERING_DOGS = "Discovering Dogs"
    VERIFYING_STATUS = "Verifying Status"
    READY = "Ready"
    ERROR = "Error"


class StartupManager:

    def __init__(self):

        self.state = None

        self.nim_manager = NIMManager()
        self.ssh_manager = SSHManager()
        self.discovery_manager = DiscoveryManager()
        self.readiness_checker = ReadinessChecks()

    def set_state(self, state):

        self.state = state

        print(f"\n[STATE] {state.value}")

    def run(self):

        try:

            self.set_state(StartupState.STARTING_NIM)

            nim_status = self.nim_manager.check_nim()

            print(f"NIM Status: {nim_status}")

            self.set_state(StartupState.CONNECTING_SSH)

            self.ssh_manager.connect("Pumbaa")
            self.ssh_manager.connect("Timon")

            self.set_state(StartupState.LAUNCHING_SERVICES)

            self.ssh_manager.launch_services("Pumbaa")
            self.ssh_manager.launch_services("Timon")

            self.set_state(StartupState.DISCOVERING_DOGS)

            dogs = self.discovery_manager.discover_dogs()

            print(f"Found {len(dogs)} robot(s)")

            self.set_state(StartupState.VERIFYING_STATUS)

            for dog in dogs:

                results = self.readiness_checker.check_robot(
                    dog["name"]
                )

                print(
                    f"{dog['name']} Ready: "
                    f"{results['ready']}"
                )

            self.set_state(StartupState.READY)

            print("\nSystem Ready")

        except Exception as e:

            self.set_state(StartupState.ERROR)

            print(e)


if __name__ == "__main__":

    startup = StartupManager()

    startup.run()