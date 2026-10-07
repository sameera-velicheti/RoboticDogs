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

from status.system_status import status


class NIMManager:

    def __init__(self):

        self.model_name = (
            "nemotron-3-nano-omni-30b-a3b-reasoning"
        )

    def check_status(self):

        return status.nim

    def start_nim(self):

        print("[NIM] Starting...")

        status.update_nim_status(
            "starting"
        )

        time.sleep(2)

        status.update_nim_status(
            "ready",
            model=self.model_name
        )

        print("[NIM] Ready")

        return True

    def stop_nim(self):

        print("[NIM] Stopping...")

        status.update_nim_status(
            "stopping"
        )

        time.sleep(1)

        status.update_nim_status(
            "offline",
            model=None
        )

        print("[NIM] Offline")

        return True


if __name__ == "__main__":

    nim = NIMManager()

    print("\nStarting NIM")

    nim.start_nim()

    print(status.get_status())

    print("\nStopping NIM")

    nim.stop_nim()

    print(status.get_status())