#!/usr/bin/env python3
"""故障模块：读取输入后挂起不退出（用于验证超时失败关闭）。"""
import sys
sys.stdin.read()
import time
time.sleep(3600)
