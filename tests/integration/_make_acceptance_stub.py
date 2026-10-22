#!/usr/bin/env python3
"""_make_acceptance_stub.py -- 生成"验收编排"测试用的 final_system.sh 变体。

只替换实验函数体（stub），不改变验收块的任何一行逻辑，用于验证：
  各项目状态 -> ACCEPTANCE 状态 -> 进程退出码
这条链路的接线是否正确。stub 版本**不得**被用来声称任何实验已执行。
"""
import io
import sys

MARKER = '# ---------------------------------------------------------------- 主流程'


def main(argv):
    src, dst = argv[1], argv[2]
    pairs = argv[3:]
    lines = []
    for pair in pairs:
        name, code = pair.split('=', 1)
        lines.append('{0}() {{ return {1}; }}'.format(name.strip(), code.strip()))
    override = '\n'.join([
        '# ==== 测试注入：以下函数体被替换为固定返回值（仅验证编排接线）====',
        'check_env() { return 0; }',
    ] + lines + ['# ==== 注入结束 ====', ''])
    text = io.open(src, encoding='utf-8').read()
    if text.count(MARKER) != 1:
        raise SystemExit('marker not found uniquely: %d' % text.count(MARKER))
    text = text.replace(MARKER, override + MARKER, 1)
    io.open(dst, 'w', encoding='utf-8').write(text)


if __name__ == '__main__':
    main(sys.argv)
