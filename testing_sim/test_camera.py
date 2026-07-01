# testing_sim/test_camera.py

import sys
import os
sys.path.insert(0, '/home/demo_user/RoboticDogs')

from ros2_bridge.ros_nodes import RosPugBridge

def main():
    print("Connecting to robot...")
    bridge = RosPugBridge()
    print("Connected.")

    print("Taking picture...")
    try:
        filepath = bridge.take_picture(save_dir='/home/demo_user/RoboticDogs/captures')
        print(f"Success! Image saved to: {filepath}")
        print(f"File size: {os.path.getsize(filepath)} bytes")
    except Exception as e:
        print(f"Failed: {e}")
    finally:
        bridge.close()
        print("Done.")

if __name__ == "__main__":
    main()