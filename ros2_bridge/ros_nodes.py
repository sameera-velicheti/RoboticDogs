import rospy
from pug_control.msg import Velocity


class RosPugBridge:
    """
    Direct ROS publisher from laptop to robot.
    No Flask, no HTTP, no robot-side changes.
    """

    def __init__(self):
        rospy.init_node("nim_laptop_bridge", anonymous=True)

        self.pub = rospy.Publisher(
            "/app_control/velocity_move",
            Velocity,
            queue_size=10
        )

        rospy.sleep(1.0)

    def cautious_walk(self, speed=0.2, duration=1.0, safety_level="medium"):
        msg = Velocity()
        msg.x = float(speed)
        msg.y = 0.0
        msg.yaw_rate = 0.0
        msg.stop = False
        self.pub.publish(msg)

    def sit(self):
        msg = Velocity()
        msg.x = 0.0
        msg.y = 0.0
        msg.yaw_rate = 0.0
        msg.stop = True
        self.pub.publish(msg)

    def stop(self):
        self.sit()

    def turn_left(self, speed=0.2, duration=1.0):
        msg = Velocity()
        msg.x = 0.0
        msg.y = 0.0
        msg.yaw_rate = float(speed)
        msg.stop = False
        self.pub.publish(msg)