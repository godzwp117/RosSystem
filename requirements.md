# requirements.md — 依赖说明

> 方案v1.2 §5.3 交付物：「本地部署说明：依赖与版本、环境脚本、构建/启动命令」。
> 实测版本见 [`environment.md`](environment.md)。

## 1. 设计原则：零额外安装

选用的 `ros:jazzy` 镜像**已自带全部依赖**，本次实现**没有在宿主机或容器内
额外安装任何软件包**。`requirements.txt` 仅用于「在无 ROS 的纯 Python 解释器上
跑 `rg_policy` 单元测试」这一可选场景。

## 2. 运行时依赖（ROS 2 侧）

| 依赖 | 用途 | 提供方 | 实测版本 |
| --- | --- | --- | --- |
| ROS 2 Jazzy | Node / Topic / Action / rclpy | `ros:jazzy` 镜像 | jazzy (noble) |
| `rclpy` | 四个节点的 Python 客户端库 | `ros-jazzy-rclpy` | 7.1.12 |
| `rmw_fastrtps_cpp` | 固定 RMW 实现 | `ros-jazzy-rmw-fastrtps-cpp` | 8.4.4 |
| `geometry_msgs` | `PatrolNavigate.Goal.target` (`PoseStamped`) | `ros-jazzy-geometry-msgs` | 5.3.8 |
| `std_msgs` | `/rg/task_info` (`String`) | `ros-jazzy-std-msgs` | 5.3.8 |
| `action_msgs` | Action 基础设施 | `ros-jazzy-action-msgs` | 2.0.4 |
| `rosidl_default_generators` / `_runtime` | 由 `.action` 生成 Python 接口 | `ros-jazzy-rosidl-default-generators` | 1.6.1 |
| `ros2cli` | `ros2 run` / `ros2 action list` / `ros2 topic echo` | `ros-jazzy-ros2cli` | 0.32.12 |
| `launch` / `launch_ros` | `*.launch.py` | `ros-jazzy-launch-ros` | 0.26.12 |
| `colcon` (+ common extensions) | 构建 | `python3-colcon-common-extensions` | 0.3.0-100 |
| cmake / g++ | 编译 `rg_interfaces` | 镜像自带 | 3.28.3 / 13.3.0 |
| PyYAML | 解析权威策略 YAML | `python3-yaml`（镜像自带） | 6.0.1 |
| pytest | 单元测试 | 镜像自带 | 7.4.4 |

### package.xml 依赖声明（已写入源码）

* `rg_interfaces` → `ament_cmake`、`rosidl_default_generators`、`rosidl_default_runtime`、`geometry_msgs`、`action_msgs`
* `rg_policy` → `python3-yaml`（**不依赖 rclpy**，刻意如此）
* `rg_gateway` → `rclpy`、`rg_interfaces`、`rg_policy`、`python3-yaml`
* `rg_demo_nodes` → `rclpy`、`rg_interfaces`、`rg_policy`、`geometry_msgs`、`std_msgs`、`launch`、`launch_ros`

## 3. 可选：纯 Python 单元测试依赖

`requirements.txt` 列出的是 `rg_policy`（唯一不 import rclpy 的包）在**没有 ROS**
的解释器上跑 `pytest` 所需的最小集合：

```
PyYAML>=6.0
pytest>=7.0
```

使用方式（例如宿主机 Ubuntu 22.04 + venv）：

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python3 -m pytest tests/unit -q -p no:cacheprovider
```

> 注意：宿主机 Python 3.10 上此路径可以工作，因为 `rg_policy` 不 import `rclpy`；
> 但 `tests/unit/test_interface_contract.py` 中依赖 `rg_interfaces` / `rg_gateway`
> 的用例会自动 `skip`（`pytest.importorskip`）。**本次交付的实际测试全部在容器内
> Python 3.12 执行**，未在宿主 3.10 上跑过，故不声称宿主结果。

## 4. 明确未安装 / 未使用

| 组件 | 状态 |
| --- | --- |
| Gazebo (Harmonic) | **未安装、未使用**（任务边界要求） |
| Nav2 | **未安装、未使用**（`/rg/nav_execute` 为自研 `navigation_sim`） |
| SROS 2 / DDS-Security | **未启用**（仅为后续预留，见 `security/README.md`） |
| 视觉模型 / 相机驱动 | **未使用**（任务边界要求） |
| Dashboard / Web UI | **未使用**（任务边界要求） |
| 任何密钥 / 私钥 | **无**（见 `.gitignore` 与 `security/README.md`） |

## 5. 网络访问需求

| 阶段 | 是否需要网络 |
| --- | --- |
| `docker pull ros:jazzy` | 需要（一次性，约 285 MiB） |
| `colcon build` | **不需要**（离线可构建） |
| 运行与测试 | **不需要**（单容器内 localhost DDS） |

> 实测细节：本机 `docker` **CLI** 无法直连 Docker Hub（`docker manifest inspect`
> 失败），但 **daemon** 可以，因此 `docker pull` 成功。这是本环境的一个真实特点，
> 排障时值得注意。

## 6. 复现安装方案（若需从零开始）

```bash
# 1) 容器运行时（宿主机需已安装 Docker）
docker pull ros:jazzy

# 2) 创建/启动本项目使用的容器（工作区 bind mount 到 /ws）
cd /home/zhangwei/project/RosSystem
scripts/container_up.sh

# 3) 构建 + 验证（全部在容器内）
scripts/build.sh
scripts/run_unit_tests.sh
scripts/run_ab_scenarios.sh
scripts/run_negative_scenarios.sh
# 或一次跑完：
scripts/run_all.sh
```

若要改为**原生 Ubuntu 24.04 + ROS 2 Jazzy**：按 ROS 2 官方文档安装
`ros-jazzy-desktop`（或 `ros-jazzy-ros-base`）与 `python3-colcon-common-extensions`，
然后把 `RG_MODE=native` 交给脚本；源码无需改动。
