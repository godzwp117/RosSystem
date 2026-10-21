import sys, time
import rclpy
from rclpy.node import Node
seconds = float(sys.argv[1])
rclpy.init()
deadline = time.monotonic() + seconds
cycle = 0
while time.monotonic() < deadline:
    nodes = [Node('m1g_churn_%d_%d' % (cycle, i)) for i in range(5)]
    end = time.monotonic() + 1.2
    while time.monotonic() < end:
        for n in nodes:
            rclpy.spin_once(n, timeout_sec=0)
    for n in nodes:
        n.destroy_node()
    cycle += 1
    time.sleep(0.5)
