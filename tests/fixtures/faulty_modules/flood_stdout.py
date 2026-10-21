#!/usr/bin/env python3
"""故障模块：持续向 stdout 洪泛输出（用于验证读取过程中限流）。"""
import sys
CHUNK = '{"x":"' + 'A' * 4096 + '"}\n'
while True:
    sys.stdout.write(CHUNK)
    sys.stdout.flush()
