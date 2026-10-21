import sys, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
seconds, lifetime = float(sys.argv[1]), float(sys.argv[2])
rclpy.init()
deadline = time.monotonic() + seconds
count = 0
while time.monotonic() < deadline:
    n = Node('m1g_blip_%d' % count)
    n.create_publisher(String, '/m1g/blip/%d' % count, 10)
    end = time.monotonic() + lifetime
    while time.monotonic() < end:
        rclpy.spin_once(n, timeout_sec=0)
    n.destroy_node()
    count += 1
    time.sleep(1.0)
