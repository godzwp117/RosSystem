import sys, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
topic, rate, seconds = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
rclpy.init()
node = Node('m1g_pub')
pub = node.create_publisher(String, topic, 200)
period = 1.0 / rate if rate > 0 else 0.05
deadline = time.monotonic() + seconds
while time.monotonic() < deadline:
    pub.publish(String(data='t'))
    rclpy.spin_once(node, timeout_sec=0)
    time.sleep(period)
