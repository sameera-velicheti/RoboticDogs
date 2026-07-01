import roslibpy
import time
import threading
import logging
import os
import base64
from datetime import datetime

logger = logging.getLogger(__name__)

ROBOT_IP = "192.168.149.1"
ROBOT_PORT = 9090
WATCHDOG_TIMEOUT = 60.0


class RosPugBridge:
    def __init__(self):
        self.client = roslibpy.Ros(host=ROBOT_IP, port=ROBOT_PORT)
        self.client.run()
        time.sleep(1.0)
        logger.info(f"Connected to ROSPug: {self.client.is_connected}")

        self.publisher = roslibpy.Topic(
            self.client,
            "/app_control/velocity_move",
            "pug_control/Velocity"
        )
        self._watchdog_timer = None

    def _start_watchdog(self, timeout):
        self._watchdog_timer = threading.Timer(timeout, self._watchdog_stop)
        self._watchdog_timer.start()

    def _cancel_watchdog(self):
        if self._watchdog_timer:
            self._watchdog_timer.cancel()
            self._watchdog_timer = None

    def _watchdog_stop(self):
        logger.warning("Watchdog triggered — forcing stop")
        self.stop()

    def _publish(self, x=0.0, y=0.0, yaw_rate=0.0, stop=False):
        self.publisher.publish(roslibpy.Message({
            "x": float(x),
            "y": float(y),
            "yaw_rate": float(yaw_rate),
            "stop": stop
        }))

    def cautious_walk(self, speed=0.15, duration=2.0, safety_level="high",
                  capture_interval=None):
        SEGMENT = 2.0
        logger.info(f"cautious_walk: speed={speed}, total_duration={duration}, segment={SEGMENT}")

        remaining = duration
        elapsed_total = 0
        last_capture_at = 0
        captured_images = []

        while remaining > 0:
            this_segment = min(SEGMENT, remaining)

            self._start_watchdog(WATCHDOG_TIMEOUT)
            self._publish(x=speed, y=0.0, yaw_rate=0.0, stop=False)
            time.sleep(this_segment)
            self._cancel_watchdog()

            self.stop()
            time.sleep(0.3)

            elapsed_total += this_segment

        # Capture every N seconds if interval is set
            if capture_interval and (elapsed_total - last_capture_at) >= capture_interval:
                try:
                    filepath = self.take_picture()
                    captured_images.append(filepath)
                    last_capture_at = elapsed_total
                    logger.info(f"Captured at {elapsed_total}s: {filepath}")
                except Exception as e:
                    logger.warning(f"Capture failed at {elapsed_total}s: {e}")

            remaining -= this_segment

        return captured_images  # return all captured images for compliance check at end

    def turn_left(self, speed=0.10, duration=1.0):
        logger.info(f"turn_left: speed={speed}, duration={duration}")
        self._start_watchdog(WATCHDOG_TIMEOUT)
        self._publish(yaw_rate=speed)
        time.sleep(duration)
        self._cancel_watchdog()
        self.stop()

    def turn_right(self, speed=0.10, duration=1.0):
        logger.info(f"turn_right: speed={speed}, duration={duration}")
        self._start_watchdog(WATCHDOG_TIMEOUT)
        self._publish(yaw_rate=-speed)
        time.sleep(duration)
        self._cancel_watchdog()
        self.stop()

    def set_pose(self, height=-0.13, pitch=0.0, roll=0.0, yaw=0.0, run_time=0.5):
        logger.info(f"set_pose: height={height}")
        pose_publisher = roslibpy.Topic(
            self.client,
            "/pug_control/pose",
            "pug_control/Pose"
        )
        pose_publisher.publish(roslibpy.Message({
            "roll": roll,
            "pitch": pitch,
            "yaw": yaw,
            "height": height,
            "x_shift": 0.0,
            "stance_x": 0.0,
            "stance_y": 0.0,
            "run_time": run_time
        }))
        time.sleep(run_time + 0.2)

    def sit(self, height=-0.15):
        logger.info(f"sit: height={height}")
        self._cancel_watchdog()
        self.stop()
        time.sleep(0.3)
        self.set_pose(height=height)

    def stop(self):
        logger.info("stop")
        self._cancel_watchdog()
        for _ in range(3):
            self._publish(x=0.0, y=0.0, yaw_rate=0.0, stop=True)
            time.sleep(0.1)

    def take_picture(self, save_dir="captures"):
        os.makedirs(save_dir, exist_ok=True)

        captured = {"data": None}

        def callback(msg):
            if captured["data"] is None:
                captured["data"] = msg["data"]

        listener = roslibpy.Topic(
            self.client,
            "/csi_camera/image_color/compressed",
            "sensor_msgs/CompressedImage"
        )
        listener.subscribe(callback)

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
        filepath = os.path.join(save_dir, f"capture_{timestamp}.jpg")

        with open(filepath, "wb") as f:
            f.write(img_bytes)

        logger.info(f"Image saved: {filepath}")
        return filepath

    def close(self):
        try:
            self.stop()
            self.publisher.unadvertise()
            self.client.terminate()
        except Exception as e:
            logger.warning(f"Error during close: {e}")