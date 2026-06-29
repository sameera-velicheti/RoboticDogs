import roslibpy
import time
import threading
import logging

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
        """Force stop if motion runs longer than timeout."""
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

    def cautious_walk(self, speed=0.115, duration=3.0, safety_level="high"):
        logger.info(f"cautious_walk: speed={speed}, duration={duration}")
        self._start_watchdog(WATCHDOG_TIMEOUT)
        self._publish(x=speed, y=0.001, yaw_rate=0.0, stop=False)
        time.sleep(duration)
        self._cancel_watchdog()
        time.sleep(0.2)  # brief pause before stop
        self.stop()

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

    def set_pose(self, height=0.05, pitch=0.0, roll=0.0, yaw=0.0, run_time=0.5):
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

    def sit(self, height=0.05):
        logger.info(f"sit: height={height}")
        self._cancel_watchdog()
        self.stop()
        time.sleep(0.3)
        self.set_pose(height=height)
        self._publish(stop=True)

    def stop(self):
        logger.info("stop")
        self._cancel_watchdog()
        for _ in range(3):  # send 3 times to ensure it registers
            self._publish(x=0.0, y=0.0, yaw_rate=0.0, stop=True)
            time.sleep(0.1)
    # Then send a hard sit
        self._publish(stop=True)

    def close(self):
        self.stop()
        self.publisher.unadvertise()
        self.client.terminate()