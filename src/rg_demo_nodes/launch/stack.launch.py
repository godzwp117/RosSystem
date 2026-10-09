"""Launch the long-running stack only: Operator + Gateway + NavigationSim.

Used by the A/B and negative-scenario harnesses, which start ``planner_node``
separately for each request so that Goal counts stay unambiguous. Also useful for
manual ``ros2 run rg_demo_nodes planner_node --ros-args -p ...`` experiments.

Run from the workspace root::

    source install/setup.bash
    ros2 launch rg_demo_nodes stack.launch.py
"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _default(path_parts):
    return os.path.join(os.getcwd(), *path_parts)


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument(
            'policy_path',
            default_value=os.environ.get(
                'RG_POLICY_PATH', _default(('config', 'task_policy.yaml'))),
            description='Authoritative TaskPolicy YAML (read-only by the Gateway).'),
        DeclareLaunchArgument(
            'audit_log_path',
            default_value=os.environ.get(
                'RG_AUDIT_LOG', _default(('logs', 'audit.jsonl'))),
            description='Gateway audit JSONL sink.'),
        DeclareLaunchArgument(
            'navsim_record_path',
            default_value=os.environ.get(
                'RG_NAVSIM_JOURNAL', _default(('logs', 'navsim_goals.jsonl'))),
            description='NavigationSim executor journal (one line per received Goal).'),
        DeclareLaunchArgument('task_id', default_value='patrol_a_001'),
        DeclareLaunchArgument('execution_timeout_sec', default_value='10.0'),
        DeclareLaunchArgument('start_operator', default_value='true'),
        DeclareLaunchArgument('simulate_delay_sec', default_value='0.0'),
    ]

    operator = Node(
        package='rg_demo_nodes',
        executable='operator_node',
        name='operator_node',
        output='screen',
        condition=IfCondition(LaunchConfiguration('start_operator')),
        parameters=[{
            'task_id': LaunchConfiguration('task_id'),
            'publish_period_sec': 2.0,
        }],
    )

    navigation_sim = Node(
        package='rg_demo_nodes',
        executable='navigation_sim',
        name='navigation_sim',
        output='screen',
        parameters=[{
            'record_path': LaunchConfiguration('navsim_record_path'),
            'simulate_delay_sec': LaunchConfiguration('simulate_delay_sec'),
        }],
    )

    gateway = Node(
        package='rg_gateway',
        executable='security_gateway',
        name='security_gateway',
        output='screen',
        parameters=[{
            'policy_path': LaunchConfiguration('policy_path'),
            'audit_log_path': LaunchConfiguration('audit_log_path'),
            'execution_timeout_sec': LaunchConfiguration('execution_timeout_sec'),
        }],
    )

    return LaunchDescription(arguments + [operator, navigation_sim, gateway])
