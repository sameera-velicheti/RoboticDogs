import os
import base64
import json
from datetime import datetime
import sys
sys.path.insert(0, '/home/demo_user/RoboticDogs')

from ros2_bridge.ros_nodes import RosPugBridge

CAPTURE_DIR = '/home/demo_user/RoboticDogs/captures'


def capture_image(bridge, label=None, save_dir=CAPTURE_DIR):
    """
    Capture a single image from the robot camera.
    Returns the filepath and metadata dict.
    """
    os.makedirs(save_dir, exist_ok=True)

    captured = {"data": None}

    import roslibpy

    def callback(msg):
        if captured["data"] is None:
            captured["data"] = msg["data"]

    listener = roslibpy.Topic(
        bridge.client,
        "/csi_camera/image_color/compressed",
        "sensor_msgs/CompressedImage"
    )
    listener.subscribe(callback)

    import time
    timeout = 5
    waited = 0
    while captured["data"] is None and waited < timeout:
        time.sleep(0.1)
        waited += 0.1

    listener.unsubscribe()

    if captured["data"] is None:
        raise RuntimeError("No image received from camera within timeout")

    img_bytes = base64.b64decode(captured["data"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"capture_{timestamp}.jpg"
    if label:
        filename = f"capture_{timestamp}_{label}.jpg"

    filepath = os.path.join(save_dir, filename)
    with open(filepath, "wb") as f:
        f.write(img_bytes)

    # Save metadata alongside the image
    metadata = {
        "timestamp": timestamp,
        "filepath": filepath,
        "label": label,
        "filesize_bytes": os.path.getsize(filepath)
    }

    meta_path = filepath.replace(".jpg", "_meta.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Captured: {filepath}")
    return filepath, metadata


if __name__ == "__main__":
    # Quick standalone test
    bridge = RosPugBridge()
    filepath, meta = capture_image(bridge, label="test")
    print(f"Saved: {filepath}")
    print(f"Metadata: {meta}")
    bridge.close()