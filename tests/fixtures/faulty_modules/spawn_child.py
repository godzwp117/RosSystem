#!/usr/bin/env python3
"""故障模块：创建子进程后自身挂起（用于验证整个进程组被清理）。"""
import subprocess
import sys
import time
sys.stdin.read()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3600)'])
print(child.pid, flush=True)
time.sleep(3600)
