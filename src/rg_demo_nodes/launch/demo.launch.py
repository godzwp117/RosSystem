"""Launch the full minimal closed loop: Operator + Gateway + NavigationSim + Planner.

Run from the workspace root so the default ``config/task_policy.yaml`` resolves::

    source install/setup.bash
    ros2 launch rg_demo_nodes demo.launch.py

A-zone (allowed) example::

    ros2 launch rg_demo_nodes demo.launch.py target_x:=1.5 target_y:=1.5

B-zone (out of region -> BLOCK) example::

    ros2 launch rg_demo_nodes demo.launch.py target_x:=9.0 target_y:=9.0

Absolute paths for ``policy_path`` / ``audit_log_path`` are recommended when not
running from the workspace root.
"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
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
        DeclareLaunchArgument('frame_id', default_value='map'),
        DeclareLaunchArgument('request_id', default_value=''),
        DeclareLaunchArgument('target_x', default_value='1.5'),
        DeclareLaunchArgument('target_y', default_value='1.5'),
        DeclareLaunchArgument('target_z', default_value='0.0'),
        DeclareLaunchArgument('expect_success', default_value='-1'),
        DeclareLaunchArgument('execution_timeout_sec', default_value='10.0'),
    ]

    operator = Node(
        package='rg_demo_nodes',
        executable='operator_node',
        name='operator_node',
        output='screen',
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

    planner = Node(
        package='rg_demo_nodes',
        executable='planner_node',
        name='planner_node',
        output='screen',
        parameters=[{
            'task_id': LaunchConfiguration('task_id'),
            'request_id': LaunchConfiguration('request_id'),
            'frame_id': LaunchConfiguration('frame_id'),
            'target_x': LaunchConfiguration('target_x'),
            'target_y': LaunchConfiguration('target_y'),
            'target_z': LaunchConfiguration('target_z'),
            'expect_success': LaunchConfiguration('expect_success'),
        }],
    )

    return LaunchDescription(arguments + [operator, navigation_sim, gateway, planner])
