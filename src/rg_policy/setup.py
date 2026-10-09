from setuptools import find_packages, setup

package_name = 'rg_policy'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'PyYAML'],
    zip_safe=True,
    maintainer='RoboGuard Base Maintainers',
    maintainer_email='roboguard-maintainers@example.invalid',
    description=(
        'ROS-free policy / event core: TaskPolicy loading, pure admission decision, '
        'duplicate + rate-limit accounting, audit event schema and JSONL sink.'
    ),
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={'console_scripts': []},
)
