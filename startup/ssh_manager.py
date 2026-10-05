"""
SSH management module.
 
For now we simulate SSH connectivity.
 
Later this should:
- Establish passwordless SSH
- Reconnect automatically
- Launch services remotely
"""

import time


class SSHManager:

    def connect(self, dog_name):
        print(f"[SSH] Connecting to {dog_name}...")
        time.sleep(1)

        return True

    def launch_services(self, dog_name):
        print(f"[SSH] Launching services on {dog_name}...")
        time.sleep(1)

        return True