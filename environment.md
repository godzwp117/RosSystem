# environment.md — 阶段一 1.3 环境核查记录（真实测量值）

> 本文所有数值均为**实际执行命令的输出**，不是预期值。原始输出见
> [`logs/environment_report.txt`](logs/environment_report.txt) 与
> [`logs/ros2_doctor_report.txt`](logs/ros2_doctor_report.txt)。
> 检查日期：2026-10-09。

## 1. 宿主机（实际检测结果）

| 项目 | 实测值 | 命令 |
| --- | --- | --- |
| 发行版 | **Ubuntu 22.04.5 LTS (jammy)** | `. /etc/os-release` |
| 内核 | `6.18.40.1-microsoft-standard-WSL2` | `uname -r` |
| 平台 | WSL2 (x86_64) | `ros2 doctor --report` |
| Python | 3.10.12 | `python3 --version` |
| `ros2` CLI | **未安装** | `command -v ros2` |
| `colcon` | **未安装** | `command -v colcon` |
| `/opt/ros` | **不存在** | `ls /opt/ros` |
| `ROS_DISTRO` | 未设置 | `printenv ROS_DISTRO` |
| `RMW_IMPLEMENTATION` | 未设置 | `printenv RMW_IMPLEMENTATION` |
| pip | 未安装 (`No module named pip`) | `python3 -m pip --version` |
| Docker | 29.7.2 (build a7dcaa6)，daemon 可用 | `docker --version` |
| 磁盘可用 | 852 GB | `df -h /` |

## 2. 关键阻塞与处置决策（已获用户确认）

方案v1.2 §1.1 指定 **Ubuntu 24.04 LTS + ROS 2 Jazzy**。
`packages.ros.org` 只为 `noble`(24.04) 发布 Jazzy 的 deb 包，**在 22.04 上无法用
apt 安装 Jazzy**（这不是配置问题，是官方不支持）。

已确认的处置（用户明确选择）：

* ROS 2 运行环境放在 **Docker `ros:jazzy` 容器**中，容器内是真正的
  Ubuntu 24.04.5 + ROS 2 Jazzy；
* 宿主机 **不安装** ROS 2，保持 Ubuntu 22.04 不变；
* 工作区 `/home/zhangwei/project/RosSystem` 通过 bind mount 挂载到容器 `/ws`；
* 所有 `colcon build`、`ros2 run`、`pytest` 均在容器内执行；
* 未安装 Gazebo / Nav2 / Dashboard。

**未做任何伪造**：宿主机上确实没有 ROS 2；所有 ROS 2 证据都来自容器内实测。

## 3. 容器实测（`ros:jazzy`）

| 项目 | 实测值 |
| --- | --- |
| 容器名 | `rg_jazzy` |
| 镜像 | `ros:jazzy` |
| 镜像 digest | `sha256:066420e07f60aa18262f2479981def87ebcfcec42eefb0c0c57c4a46098348ca` |
| 镜像大小 | 298,971,213 bytes (~285 MiB) |
| 容器内 OS | **Ubuntu 24.04.5 LTS (noble)** |
| 容器内 Python | 3.12.3 |
| `ROS_DISTRO` | `jazzy` |
| `RMW_IMPLEMENTATION` | `rmw_fastrtps_cpp` |
| RMW 中间件（doctor 实测） | `rmw_fastrtps_cpp` |
| `ROS_DOMAIN_ID` | 42 |
| `ROS_AUTOMATIC_DISCOVERY_RANGE` | `LOCALHOST`（单容器内确定性发现） |
| 工作目录 | `/ws`（= 宿主 `/home/zhangwei/project/RosSystem`） |

## 4. 依赖包版本（容器内 `dpkg-query` 实测）

| 包 | 版本 |
| --- | --- |
| `ros-jazzy-rclpy` | 7.1.12-1noble.20260902.053513 |
| `ros-jazzy-rmw-fastrtps-cpp` | 8.4.4-1noble.20260902.041916 |
| `ros-jazzy-geometry-msgs` | 5.3.8-1noble.20260902.030745 |
| `ros-jazzy-std-msgs` | 5.3.8-1noble.20260902.022418 |
| `ros-jazzy-action-msgs` | 2.0.4-1noble.20260902.015426 |
| `ros-jazzy-rosidl-default-generators` | 1.6.1-1noble.20260902.021422 |
| `ros-jazzy-ros2cli` | 0.32.12-1noble.20260902.102710 |
| `ros-jazzy-launch-ros` | 0.26.12-1noble.20260902.054847 |
| `python3-colcon-common-extensions` | 0.3.0-100 |
| cmake | 3.28.3 |
| g++ | 13.3.0 |
| PyYAML | 6.0.1 |
| pytest | 7.4.4 |
| 已安装 `ros-jazzy-*` 包总数 | 201 |

镜像内**已经包含**全部所需依赖，本次实现**没有额外 apt 安装任何软件包**。
（只需 `docker pull ros:jazzy`。）

## 5. 报告的实际结论

* ✅ ROS 2 Jazzy 真实可用（Node / Topic / Action / rclpy / colcon 全部实测通过）。
* ✅ RMW 固定为 `rmw_fastrtps_cpp`，版本已记录。
* ✅ 版本冻结，不依赖硬件、摄像头或视觉模型。
* ⚠️ 宿主机为 Ubuntu 22.04，与方案v1.2 §1.1 的「Ubuntu 24.04 原生」建议不一致；
  已用容器满足同一 distro 要求。若后续必须原生 24.04，需要另建 24.04 主机或
  在宿主宿装 24.04，本交付物本身不做改动即可迁移（只需 `colcon build`）。
* ⚠️ WSL2 环境：所有节点在同一容器内运行（共享 netns/ipc），已避开 WSL2 跨主机
  DDS 发现问题。跨主机/跨容器 DDS 发现**未验证**，见 README「已知限制」。
* ❌ SROS 2 (DDS-Security) **未启用**，见 [`security/README.md`](security/README.md)。
* ❌ Nav2 / Gazebo **未安装、未验证**。

## 6. 复现方式

```bash
cd /home/zhangwei/project/RosSystem
scripts/container_up.sh          # 幂等：拉取镜像并创建/启动 rg_jazzy
scripts/run_all.sh               # build -> 单元测试 -> A/B -> 负例
```

Git commit：本工作区**不是 git 仓库**（`git rev-parse HEAD` 无输出），因此本记录
无法附带 commit hash；版本冻结依据是上面的镜像 digest 与 deb 包版本。
