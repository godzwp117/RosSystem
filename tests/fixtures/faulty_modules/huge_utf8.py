#!/usr/bin/env python3
"""故障模块：输出多字节 UTF-8（用于验证按字节而非字符计数）。"""
import sys
sys.stdin.read()
sys.stdout.write('中' * 100000)   # 每字符 3 字节 = 300000 字节
sys.stdout.flush()
