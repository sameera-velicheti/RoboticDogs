"""
NIM lifecycle management.

Current Version:
- Mock implementation
- No Docker calls yet

Future Version:
- Start NIM container
- Stop NIM container
- Check model health endpoint
- Report status back to UI
"""

import time


class NIMManager:

    def __init__(self):

        self.status = "offline"

        self.model_name = (
            "nemotron-3-nano-omni-30b-a3b-reasoning"
        )

    def check_status(self):
        """
        Return current NIM status.

        Future:
        Check Docker container
        Check NIM health endpoint
        """

        return {
            "status": self.status,
            "model": self.model_name if self.status == "ready" else None
        }

    def start_nim(self):
        """
        Start NIM.

        Future:
        docker compose up -d
        """

        print("[NIM] Starting...")

        self.status = "starting"

        time.sleep(2)

        self.status = "ready"

        print("[NIM] Ready")

        return True

    def stop_nim(self):
        """
        Stop NIM.

        Future:
        docker compose down
        """

        print("[NIM] Stopping...")

        self.status = "stopping"

        time.sleep(1)

        self.status = "offline"

        print("[NIM] Offline")

        return True


if __name__ == "__main__":

    nim = NIMManager()

    print("\nCheck:")
    print(nim.check_status())

    print("\nStarting:")
    nim.start_nim()

    print(nim.check_status())

    print("\nStopping:")
    nim.stop_nim()

    print(nim.check_status())