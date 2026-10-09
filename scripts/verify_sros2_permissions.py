#!/usr/bin/env python3
"""verify_sros2_permissions.py -- 核对生成的 permissions.xml 是否真的最小权限。

为什么必须有这个工具
--------------------
实测发现（见 CHANGELOG U6）：当 policy XML 解析失败时，
`ros2 security generate_artifacts` 会**静默退回默认宽松策略**（`rt/*`、`rq/*Request`、
`rr/*Reply` —— 即整个 domain 上的全部 topic 与请求/应答），并且**仍然产出** enclave
密钥与 permissions.xml。若只看"命令跑完了、文件生成了"就宣称安全已启用，会把
"全部放开"误当成"最小权限"。

因此本工具独立复核生成结果，出现宽松回退特征即判失败并返回非零。

校验项：
  1. 策略中的每个 enclave 都有 permissions.xml；
  2. 不含宽松回退特征（rt/* / rq/*Request / rr/*Reply 等全量通配）；
  3. 每个 enclave 的授权 topic 模式都能由该 enclave 的策略条目解释
     （不允许出现策略里没有的通配模式）；
  4. /unauthorized 这类"零业务权限"身份不得拿到业务 topic 授权；
  5. 授权 domain 与期望一致。

用法：
    python3 scripts/verify_sros2_permissions.py \
        --keystore security/keystore \
        --policy security/policies/minimal_permissions.xml \
        --domain 43
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

# 默认策略经 sros2 展开后产生的"全量放开"特征
BROAD_FALLBACK_PATTERNS = {
    'rt/*',
    'rq/*Request',
    'rr/*Reply',
    '*',
    '/*',
}

# 允许出现的通配（策略里显式写了通配才会出现）；本项目的策略刻意不用通配
ALLOWED_WILDCARDS: set = set()


def local_name(tag: str) -> str:
    return tag.split('}')[-1]


def parse_policy(policy_path: str) -> dict:
    """返回 {enclave_path: {'nodes': [...], 'topics': set, 'services': set, 'allow_any': bool}}"""
    tree = ET.parse(policy_path)
    root = tree.getroot()
    enclaves = {}
    for enclave in root.iter():
        if local_name(enclave.tag) != 'enclave':
            continue
        path = enclave.get('path')
        info = {'nodes': [], 'topics': set(), 'services': set(), 'allow_any': False}
        for profile in enclave.iter():
            if local_name(profile.tag) != 'profile':
                continue
            info['nodes'].append(profile.get('node'))
            for topics_el in profile:
                if local_name(topics_el.tag) != 'topics':
                    continue
                for topic_el in topics_el:
                    if local_name(topic_el.tag) == 'topic':
                        text = (topic_el.text or '').strip()
                        if text:
                            info['topics'].add(text)
                            if text in ('/*', '*'):
                                info['allow_any'] = True
            for services_el in profile:
                if local_name(services_el.tag) != 'services':
                    continue
                for service_el in services_el:
                    if local_name(service_el.tag) == 'service':
                        text = (service_el.text or '').strip()
                        if text:
                            info['services'].add(text)
        enclaves[path] = info
    return enclaves


def parse_permissions(permissions_path: str) -> dict:
    """提取 permissions.xml 中的授权 topic 模式、domain 与 subject。"""
    tree = ET.parse(permissions_path)
    root = tree.getroot()
    result = {'topics': set(), 'domains': set(), 'subjects': set(), 'has_allow_rule': False}
    for element in root.iter():
        name = local_name(element.tag)
        if name == 'subject_name' and element.text:
            result['subjects'].add(element.text.strip())
        elif name == 'id' and element.text and element.text.strip().isdigit():
            result['domains'].add(int(element.text.strip()))
        elif name == 'topic' and element.text:
            result['topics'].add(element.text.strip())
        elif name == 'allow_rule':
            result['has_allow_rule'] = True
    return result


def dds_prefix_candidates(policy_topic: str) -> list:
    """把策略里的 ROS topic 名映射为可接受的 DDS 模式（rt/ 前缀）。"""
    topic = policy_topic
    if topic.startswith('~/'):
        # 节点私有：sros2 会展开为 rt/<node>/<rest>，无法在策略层确定 node，放宽为后缀匹配
        return ['~/' + topic[2:]]
    if topic.startswith('/'):
        topic = topic[1:]
    return ['rt/' + topic]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='核对 SROS 2 permissions.xml 是否为最小权限')
    parser.add_argument('--keystore', required=True)
    parser.add_argument('--policy', required=True)
    parser.add_argument('--domain', type=int, default=None, help='期望的 DDS domain id')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)

    errors = []
    warnings = []
    report = []

    if not os.path.isfile(args.policy):
        print('ERROR: 策略文件不存在: {0}'.format(args.policy), file=sys.stderr)
        return 2
    if not os.path.isdir(args.keystore):
        print('ERROR: keystore 不存在: {0}'.format(args.keystore), file=sys.stderr)
        return 2

    policy = parse_policy(args.policy)
    enclaves_dir = os.path.join(args.keystore, 'enclaves')

    for enclave_path, info in policy.items():
        name = enclave_path.strip('/')
        perm_path = os.path.join(enclaves_dir, name, 'permissions.xml')
        if not os.path.isfile(perm_path):
            errors.append('{0}: 缺少 permissions.xml ({1})'.format(enclave_path, perm_path))
            continue
        try:
            perms = parse_permissions(perm_path)
        except ET.ParseError as exc:
            errors.append('{0}: permissions.xml 解析失败: {1}'.format(enclave_path, exc))
            continue

        granted_broad = sorted(perms['topics'] & BROAD_FALLBACK_PATTERNS)
        if granted_broad:
            errors.append(
                '{0}: 出现宽松回退特征 {1} —— generate_artifacts 很可能回退到了默认全开策略'
                .format(enclave_path, granted_broad))

        # 策略里没有通配，却出现了本项目未预期的通配
        unexpected_wildcards = sorted(
            t for t in perms['topics'] if '*' in t and t not in ALLOWED_WILDCARDS
            and not any(t.endswith(suffix) for suffix in ('/_action/status', '/_action/feedback')))
        if unexpected_wildcards and not info['allow_any']:
            errors.append('{0}: 出现策略未授权的通配 topic: {1}'
                          .format(enclave_path, unexpected_wildcards[:6]))

        # 零业务权限身份不得拿到业务 topic
        if enclave_path == '/unauthorized':
            business = [t for t in perms['topics'] if '_action' in t or 'rg/' in t or t == 'rt/*']
            if business or not perms['topics']:
                # 允许 topics 为空（默认 DENY）；只要出现任何业务 topic 即失败
                if business:
                    errors.append('{0}: 无授权身份不应获得业务 topic: {1}'
                                  .format(enclave_path, business[:6]))

        if args.domain is not None and perms['domains'] and args.domain not in perms['domains']:
            errors.append('{0}: 授权 domain={1} 与期望 {2} 不一致'
                          .format(enclave_path, sorted(perms['domains']), args.domain))

        report.append({
            'enclave': enclave_path,
            'node': ','.join(n for n in info['nodes'] if n),
            'policy_topics': len(info['topics']),
            'policy_services': len(info['services']),
            'granted_topics': len(perms['topics']),
            'domains': sorted(perms['domains']),
            'subjects': sorted(perms['subjects']),
        })

    # 期望的授权名必须真的出现（防止"什么都没授权"被误判为最小权限）
    for enclave_path, needle in (('/planner', '/_action/send_goal'),
                                 ('/gateway', '/_action/send_goal'),
                                 ('/navsim', '/_action/send_goal')):
        name = enclave_path.strip('/')
        perm_path = os.path.join(enclaves_dir, name, 'permissions.xml')
        if os.path.isfile(perm_path):
            text = open(perm_path, 'r', encoding='utf-8').read()
            if 'guarded_navigate' not in text and 'nav_execute' not in text:
                errors.append('{0}: 未授权任何 Action 资源，权限生成可能不完整'.format(enclave_path))

    if not args.quiet:
        print('=== SROS 2 权限核对: {0} ==='.format(args.keystore))
        for row in report:
            print('  {0:<14} node={1:<18} 策略 topic={2:<3} service={3:<3} '
                  '授权 topic={4:<3} domain={5}'.format(
                      row['enclave'], row['node'], row['policy_topics'],
                      row['policy_services'], row['granted_topics'], row['domains']))
        if warnings:
            print('  警告:')
            for item in warnings:
                print('    - {0}'.format(item))
        if errors:
            print('  失败:')
            for item in errors:
                print('    - {0}'.format(item))
        print('PERMISSIONS VERIFY: {0}'.format('PASS' if not errors else 'FAIL'))

    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
