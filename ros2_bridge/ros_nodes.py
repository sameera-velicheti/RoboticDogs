import roslibpy
import time
import threading
import logging

logger = logging.getLogger(__name__)

ROBOT_IP = "192.168.149.1"
ROBOT_PORT = 9090
WATCHDOG_TIMEOUT = 4.0  


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

    def cautious_walk(self, speed=0.10, duration=2.0, safety_level="high"):
        logger.info(f"cautious_walk: speed={speed}, duration={duration}")
        self._start_watchdog(WATCHDOG_TIMEOUT)
        self._publish(x=speed)
        time.sleep(duration)
        self._cancel_watchdog()
        self.stop()

    def turn_left(self, speed=0.10, duration=1.0):
        logger.info(f"turn_left: speed={speed}, duration={duration}")
        self._start_watchdog(WATCHDOG_TIMEOUT)
        self._publish(yaw_rate=speed)
        time.sleep(duration)
        self._cancel_watchdog()
        self.stop()

    def sit(self):
        logger.info("sit")
        self._cancel_watchdog()
        self._publish(stop=True)

    def stop(self):
        logger.info("stop")
        self._cancel_watchdog()
        self._publish(x=0.0, y=0.0, yaw_rate=0.0, stop=False)

    def close(self):
        self.stop()
        self.publisher.unadvertise()
        self.client.terminate()