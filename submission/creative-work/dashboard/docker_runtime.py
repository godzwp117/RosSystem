"""docker_runtime.py -- 真实 Docker / ROS 2 Jazzy 运行条件探测（P0-2）。

为什么需要它
============
原先 `online_possible = docker_exists and workspace_built` 过于宽松：
宿主机可能完全没有 ROS 2，而正式架构是 **ROS 2 在容器里跑**。
把"宿主机有 install/setup.bash"当成在线可用，会在真实演示时直接失败。

本模块只做**探测**，不启动容器，不删除任何别人的容器。
探测结论供控制台显示 ONLINE READY 或 UNAVAILABLE（附具体原因）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

#: 作品默认使用的运行镜像（可被环境变量覆盖）
DEFAULT_IMAGE = os.environ.get('ROS_IMAGE', 'ros:jazzy')
#: 作品默认使用的在线 Domain（可被覆盖）
DEFAULT_DOMAIN = os.environ.get('ROS_ONLINE_DOMAIN', '77')


def _run(argv, timeout=15):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or ''), (proc.stderr or '')
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, '', str(exc)


def docker_available():
    """docker 命令存在且 daemon 可连接。"""
    if shutil.which('docker') is None:
        return False, '未检测到 docker 命令'
    code, _out, err = _run(['docker', 'info'])
    if code != 0:
        return False, 'docker daemon 不可连接: %s' % (err.strip()[:120] or 'unknown')
    return True, ''


def image_present(image=DEFAULT_IMAGE):
    if shutil.which('docker') is None:
        return False, '未检测到 docker 命令'
    code, out, _err = _run(['docker', 'image', 'inspect', image])
    return (code == 0), ('' if code == 0 else '镜像不存在: %s' % image)


def container_ros_ok(image=DEFAULT_IMAGE):
    """在**临时一次性容器**里验证 ROS 2 Jazzy 可用（不挂载、不驻留）。"""
    code, out, err = _run([
        'docker', 'run', '--rm', '--network', 'none', image,
        'bash', '-lc',
        'set +u; source /opt/ros/jazzy/setup.bash; set -u; '
        'echo ROS_DISTRO=$ROS_DISTRO; '
        'python3 -c "import jsonschema" 2>/dev/null || echo NO_JSONSCHEMA'],
        timeout=120)
    if code != 0:
        return False, '无法在容器内验证 ROS 2: %s' % (err.strip()[:160] or out.strip()[:160])
    if 'ROS_DISTRO=jazzy' not in out:
        return False, '容器内 ROS_DISTRO 不是 jazzy'
    # jsonschema 由作品 build-runtime.sh 在镜像内安装；缺失时明确报告
    return True, ('' if 'NO_JSONSCHEMA' not in out else '容器内缺少 jsonschema（需先运行 build-runtime.sh）')


def probe(workspace_root):
    """综合探测：返回结构化结论 + 逐条原因。"""
    reasons = []
    env_complete = True
    docker_ok, why = docker_available()
    if not docker_ok:
        reasons.append(why)
    img_ok, why_img = image_present()
    if not img_ok:
        reasons.append(why_img)

    # 完整作品包把源码放在 runtime/ 下；仓库布局则直接在根。
    candidates = (os.path.join(workspace_root, 'runtime', 'scripts', 'final_system.sh'),
                  os.path.join(workspace_root, 'scripts', 'final_system.sh'))
    ws_root = ''
    for cand in candidates:
        if os.path.exists(cand):
            ws_root = os.path.dirname(os.path.dirname(cand))
            break
    ws_ready = bool(ws_root)
    if not ws_ready:
        reasons.append('作品内缺少 scripts/final_system.sh（不是完整在线包）')

    ros_ok, why_ros = (False, '未探测')
    if docker_ok and img_ok:
        ros_ok, why_ros = container_ros_ok()
        if not ros_ok:
            reasons.append(why_ros)
        elif why_ros:
            # 例如容器内缺 jsonschema：运行条件不完整，不得判 ONLINE READY
            reasons.append(why_ros)
            env_complete = False

    return {
        'docker_cli': shutil.which('docker') is not None,
        'docker_daemon': docker_ok,
        'image': DEFAULT_IMAGE,
        'image_present': img_ok,
        'runtime_source_present': ws_ready,
        'runtime_workspace_root': ws_root or None,
        'container_ros_jazzy_ok': ros_ok,
        'online_domain': DEFAULT_DOMAIN,
        'online_possible': bool(docker_ok and img_ok and ros_ok and ws_ready
                                and env_complete),
        'blocked_reasons': reasons,
        'note': ('在线模式需要 docker daemon + 运行镜像 + 容器内 ROS 2 Jazzy + '
                 '作品内完整 runtime 源码。缺任何一项即 UNAVAILABLE，不会伪报 ONLINE READY。'),
    }


if __name__ == '__main__':
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(json.dumps(probe(root), ensure_ascii=False, indent=2))
