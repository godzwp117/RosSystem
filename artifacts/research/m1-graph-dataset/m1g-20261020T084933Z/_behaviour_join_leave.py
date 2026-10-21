import sys, time
import rclpy
from rclpy.node import Node
seconds = float(sys.argv[1])
rclpy.init()
deadline = time.monotonic() + seconds
while time.monotonic() < deadline:
    n = Node('m1g_visitor')
    end = time.monotonic() + 8
    while time.monotonic() < end:
        rclpy.spin_once(n, timeout_sec=0)
    n.destroy_node()
    time.sleep(6)
