import sys, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
seconds = float(sys.argv[1])
rclpy.init()
node = Node('m1g_recon')
pubs = []
deadline = time.monotonic() + seconds
round_no = 0
while time.monotonic() < deadline:
    p = node.create_publisher(String, '/m1g/recon/probe_%d' % round_no, 10)
    pubs.append(p)
    end = time.monotonic() + 2.0
    while time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0)
    round_no += 1
    time.sleep(0.4)
