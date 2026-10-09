"""Shared pytest setup for the unit tests.

Makes ``rg_policy`` importable directly from ``src/`` so the pure-Python core can
be tested even without a colcon build or a sourced ROS environment. When the
workspace *is* built and sourced, the installed copy is used instead -- either
way the assertions are identical.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, 'src')

for package in ('rg_policy',):
    candidate = os.path.join(SRC, package)
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)

WORKSPACE_ROOT = ROOT
CONFIG_DIR = os.path.join(ROOT, 'config')
SCENARIO_CONFIG_DIR = os.path.join(CONFIG_DIR, 'scenarios')
DEFAULT_POLICY_PATH = os.path.join(CONFIG_DIR, 'task_policy.yaml')
ACTION_FILE = os.path.join(SRC, 'rg_interfaces', 'action', 'PatrolNavigate.action')
