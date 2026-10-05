"""
Robot discovery module.

Later:
- Ping scan
- ARP scan
- Verify ROS services
"""

import time


class DiscoveryManager:

    def discover_dogs(self):

        print("[DISCOVERY] Searching for robots...")
        time.sleep(2)

        return [
            {
                "name": "Pumbaa",
                "ip": "192.168.0.60"
            },
            {
                "name": "Timon",
                "ip": "192.168.0.85"
            }
        ]