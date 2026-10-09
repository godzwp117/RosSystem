import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'rg_demo_nodes'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='RoboGuard Base Maintainers',
    maintainer_email='roboguard-maintainers@example.invalid',
    description='Minimal business nodes: operator, planner, navigation_sim.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'operator_node = rg_demo_nodes.operator_node:main',
            'planner_node = rg_demo_nodes.planner_node:main',
            'navigation_sim = rg_demo_nodes.navigation_sim:main',
        ],
    },
)
