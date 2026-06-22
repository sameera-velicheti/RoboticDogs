import rospy
from geometry_msgs.msg import Twist
import time


class RosPugBridge:
    def __init__(self):
        rospy.init_node('ros_pug_bridge', anonymous=True)
        self.publisher = rospy.Publisher('/cmd_vel', Twist, queue_size=10)
        rospy.loginfo("ROS1 Bridge Node Initialized")

    def cautious_walk(self, speed=0.1, duration=2.0, safety_level="medium"):
        rospy.loginfo(f"cautious_walk | speed={speed}, duration={duration}, safety={safety_level}")

        msg = Twist()
        msg.linear.x = float(speed)
        msg.angular.z = 0.0

        start = time.time()

        rate = rospy.Rate(10)  # 10 Hz

        while time.time() - start < duration and not rospy.is_shutdown():
            self.publisher.publish(msg)
            rate.sleep()

        # STOP
        self.publisher.publish(Twist())
        rospy.loginfo("Robot stopped safely")