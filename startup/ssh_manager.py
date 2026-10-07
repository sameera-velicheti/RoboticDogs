"""
SSH connection manager.

Current version:
- Mock implementation

Future version:
- Paramiko
- Passwordless SSH
- Service startup
"""

from status.system_status import status


class SSHManager:

    def connect(self, dog_name):

        print(f"[SSH] Connected to {dog_name}")

        status.update_dog(
            dog_name,
            connected=True
        )

        return True

    def launch_services(self, dog_name):

        print(f"[SSH] Services started on {dog_name}")

        status.update_dog(
            dog_name,
            services_running=True
        )

        return True