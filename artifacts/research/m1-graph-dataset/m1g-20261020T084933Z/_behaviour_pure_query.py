import sys, time
import rclpy
from rclpy.node import Node
seconds = float(sys.argv[1])
rclpy.init()
node = Node('m1g_query')
deadline = time.monotonic() + seconds
while time.monotonic() < deadline:
    node.get_node_names()
    node.get_topic_names_and_types()
    node.get_service_names_and_types()
    end = time.monotonic() + 0.5
    while time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0)
