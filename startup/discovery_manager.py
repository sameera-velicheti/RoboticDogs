"""
Dog discovery module.

Current version:
- Mock implementation

Future version:
- Network scan
- Device discovery
- Automatic robot registration
"""

from status.system_status import status


class DiscoveryManager:

    def discover_dogs(self):

        print("[DISCOVERY] Looking for dogs...")

        discovered_dogs = [
            {
                "name": "Pumbaa",
                "ip": "192.168.0.60"
            },
            {
                "name": "Timon",
                "ip": "192.168.0.85"
            }
        ]

        for dog in discovered_dogs:

            status.update_dog(
                dog["name"],
                discovered=True
            )

        return discovered_dogs