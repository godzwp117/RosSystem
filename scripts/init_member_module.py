#!/usr/bin/env python3
"""从模板初始化一个成员研究模块目录。

用法：
    python3 scripts/init_member_module.py --module comm_risk --dest modules/my_comm

只做**文件复制 + 模块身份替换**，不引入代码生成框架。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(REPO, 'templates', 'member_module')
MODULES = ('comm_risk', 'identity_trust', 'task_risk')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='初始化成员模块目录')
    parser.add_argument('--module', required=True, choices=MODULES)
    parser.add_argument('--dest', required=True, help='目标目录（相对仓库根）')
    parser.add_argument('--force', action='store_true',
                        help='目标已存在时覆盖（默认拒绝，避免覆盖他人工作）')
    args = parser.parse_args(argv)

    dest = args.dest if os.path.isabs(args.dest) else os.path.join(REPO, args.dest)
    if os.path.exists(dest) and not args.force:
        print('ERROR: 目标目录已存在：{0}'.format(args.dest), file=sys.stderr)
        print('       默认不覆盖（避免影响其他成员的工作）。'
              '确需覆盖请显式加 --force。', file=sys.stderr)
        return 3

    if not os.path.isdir(TEMPLATE):
        print('ERROR: 模板目录不存在：{0}'.format(TEMPLATE), file=sys.stderr)
        return 2

    os.makedirs(dest, exist_ok=True)
    written = []
    for name in ('module.py', 'README.md', 'example_config.yaml', 'test_module.py'):
        src = os.path.join(TEMPLATE, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(dest, name)
        shutil.copy2(src, dst)
        written.append(name)

    # 在 module.py 顶部记录本模块身份，便于成员少改一处
    module_py = os.path.join(dest, 'module.py')
    if os.path.isfile(module_py):
        with open(module_py, encoding='utf-8') as handle:
            text = handle.read()
        text = text.replace(
            "MODULE_DIR = None  # 由 init 工具或你手工设置（用于定位仓库根）；保持 None 也可运行",
            "MODULE_DIR = None\n\n#: 本模块身份（由 scripts/init_member_module.py 写入）\nDEFAULT_MODULE = {0!r}".format(
                args.module))
        with open(module_py, 'w', encoding='utf-8') as handle:
            handle.write(text)

    print('已创建 {0}（模块身份 {1}）：'.format(args.dest, args.module))
    for name in written:
        print('  {0}'.format(os.path.join(args.dest, name)))
    print('\n下一步：')
    print('  1) 实现 {0}/module.py 的 analyse()'.format(args.dest))
    print('  2) 把 {0}/example_config.yaml 的片段合并进你的 '
          'config/team_modules.local.yaml'.format(args.dest))
    print('  3) 运行 python3 scripts/check_member_module.py --module {0} '
          '--config config/team_modules.local.yaml'.format(args.module))
    print('\n注意：模板默认**不会**输出 NORMAL/AUTHORIZED/ALLOW_RECOMMENDED，')
    print('      未实现算法时以退出码 3 安全失败 —— 这是刻意设计。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
