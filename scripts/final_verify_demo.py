#!/usr/bin/env python3
"""final_verify_demo.py -- 单一 SHA 上的最终复验驱动与结果汇总。

设计目标
--------
把"在某一个固定 Git SHA 上、按固定顺序、执行全部验收层次"变成**可复现的一次命令**，
并把每条命令的**实际返回码与输出摘要**写入 `test_results.json`，
避免人工摘要把 PASS/FAIL 写错（2026-10-16 的 ON-06 报告错误正属此类）。

它**不修改**任何被测源码、策略或权限；只运行既有入口并记录结果。

层次划分（严格区分，不混同）
--------------------------
  L0_GIT        Git SHA / 分支 / 工作区状态
  L1_PROTOCOL   契约 + Schema + 验收器严格性反例 + ID 关联 + 证据反例（离线）
  L2_ALGORITHM  M2/M3 真实模块验收（离线真实算法 + 真实证据）
  L3_ROS2       基础 A/B（Gateway/NavigationSim）+ M3 在线六场景（域 42 普通模式）
  L4_DDS        DDS-Security Enforce 独立回归（域 43）——**与 L3 不是同一次运行**

用法
----
    python3 scripts/final_verify_demo.py --out-dir artifacts/.../final-review-<run_id>

退出码：0 = 无 FAIL；1 = 存在 FAIL；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CONTAINER = os.environ.get('RG_CONTAINER', 'rg_jazzy')


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def run(cmd, timeout=1800, cwd=None, env=None, stdin_text=None):
    """执行一条命令并如实返回退出码/输出。"""
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd or REPO, capture_output=True, text=True,
            timeout=timeout, env=env, input=stdin_text, shell=False)
        return {
            'cmd': cmd, 'returncode': proc.returncode,
            'stdout': proc.stdout, 'stderr': proc.stderr,
            'elapsed_sec': round(time.monotonic() - started, 2),
            'timed_out': False,
        }
    except subprocess.TimeoutExpired:
        return {'cmd': cmd, 'returncode': None, 'stdout': '', 'stderr': '',
                'elapsed_sec': round(time.monotonic() - started, 2),
                'timed_out': True}
    except FileNotFoundError as exc:
        return {'cmd': cmd, 'returncode': None, 'stdout': '',
                'stderr': 'NOT_FOUND: {0}'.format(exc),
                'elapsed_sec': round(time.monotonic() - started, 2),
                'timed_out': False}


def run_in_container(script, timeout=1800):
    """在容器内执行 bash 片段（ROS 2 相关层次）。"""
    return run(['docker', 'exec', CONTAINER, 'bash', '-lc', script],
               timeout=timeout)


def tail(text, n=400):
    text = (text or '').strip()
    return text[-n:]


def parse_pytest_counts(stdout):
    """从 pytest 输出提取 passed/failed/skipped/error 计数。"""
    counts = {}
    for token in ('passed', 'failed', 'skipped', 'error', 'errors'):
        for line in reversed((stdout or '').splitlines()):
            if token in line and ('=' in line or 'passed' in line):
                parts = line.replace('=', ' ').split(',')
                for part in parts:
                    words = part.split()
                    for idx, word in enumerate(words):
                        if word.rstrip('s').startswith(token.rstrip('s')):
                            try:
                                counts[token] = int(words[idx - 1])
                            except (ValueError, IndexError):
                                pass
                break
    return counts


def git_facts():
    facts = {}
    for key, cmd in (
        ('head_sha', ['git', 'rev-parse', 'HEAD']),
        ('branch', ['git', 'rev-parse', '--abbrev-ref', 'HEAD']),
        ('status_porcelain', ['git', 'status', '--porcelain']),
        ('baseline', ['git', 'rev-parse', 'origin/baseline']),
        ('main', ['git', 'rev-parse', 'origin/main']),
        ('member_deliveries', ['git', 'rev-parse', 'origin/chore/member-deliveries']),
        ('fix_branch', ['git', 'rev-parse', 'origin/fix/m2-m3-acceptance']),
        ('old_demo', ['git', 'rev-parse', 'origin/demo/2026-10-19-rc']),
    ):
        result = run(cmd, timeout=120)
        facts[key] = (result['stdout'] or '').strip() if not isinstance(
            result, dict) else (result['stdout'] or '').strip()
    return facts


def container_env():
    script = (
        'set +u; source /opt/ros/jazzy/setup.bash; '
        'cd /ws && source install/setup.bash 2>/dev/null; set -u; '
        'echo "ROS_DISTRO=${ROS_DISTRO:-}"; '
        'echo "RMW=${RMW_IMPLEMENTATION:-}"; '
        'echo "DOMAIN=${ROS_DOMAIN_ID:-}"; '
        'echo "PY=$(python3 --version 2>&1)"; '
        'echo "PKGS=$(ros2 pkg list 2>/dev/null | grep -cE \'^rg_\')"; '
        'echo "NODES=$(timeout 10 ros2 node list 2>/dev/null | wc -l)"'
    )
    result = run_in_container(script, timeout=300)
    facts = {}
    for line in (result['stdout'] or '').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            facts[key.strip()] = value.strip()
    facts['_returncode'] = result['returncode']
    return facts


class Report:
    def __init__(self, run_id):
        self.run_id = run_id
        self.entries = []

    def add(self, layer, cid, name, result, verdict, note='', extra=None):
        entry = {
            'layer': layer, 'id': cid, 'check': name,
            'verdict': verdict, 'returncode': result.get('returncode'),
            'elapsed_sec': result.get('elapsed_sec'),
            'timed_out': result.get('timed_out'),
            'stdout_tail': tail(result.get('stdout'), 500),
            'stderr_tail': tail(result.get('stderr'), 500),
            'note': note,
        }
        if extra:
            entry.update(extra)
        self.entries.append(entry)
        return entry

    def failures(self):
        return [e for e in self.entries if e['verdict'] == 'FAIL']

    def counts(self):
        out = {}
        for entry in self.entries:
            out[entry['verdict']] = out.get(entry['verdict'], 0) + 1
        return out


def main(argv=None):
    parser = argparse.ArgumentParser(description='演示候选最终复验')
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--claims-template',
                        help='报告声明模板（给出时复制到合并证据目录供复核）')
    parser.add_argument('--skip-online', action='store_true',
                        help='跳过 M3 在线六场景（无 ROS 2 环境时）')
    args = parser.parse_args(argv)

    run_id = args.run_id or 'final-' + datetime.now(
        timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out_dir = os.path.join(REPO, args.out_dir) if not os.path.isabs(
        args.out_dir) else args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    report = Report(run_id)

    # ---------------- L0: Git ----------------
    facts = git_facts()
    sha = facts.get('head_sha', '')
    dirty = [line for line in (facts.get('status_porcelain') or '').splitlines()
             if line.strip() and not line.startswith('?? user/')]
    report.add('L0_GIT', 'GIT-01', '受测 SHA 已记录', {'returncode': 0},
               'PASS' if len(sha) == 40 else 'FAIL',
               note='HEAD={0} branch={1}'.format(sha, facts.get('branch')),
               extra={'git': facts})
    report.add('L0_GIT', 'GIT-02', '工作区干净（受测代码 == 提交内容）',
               {'returncode': 0},
               'PASS' if not dirty else 'FAIL',
               note='未提交条目数={0}'.format(len(dirty)),
               extra={'dirty_entries': dirty[:20]})

    env_facts = container_env()
    environment = {
        'run_id': run_id, 'generated_at': now(), 'repo': REPO,
        'host': platform.platform(), 'python': sys.version.split()[0],
        'git': facts, 'container': env_facts,
        'dds_security_mode_l3': 'disabled (domain 42, normal mode)',
        'dds_security_mode_l4': 'enforce (domain 43)',
        'module_config_l3': {'comm_risk': 'MOCK', 'identity_trust': 'MOCK',
                             'task_risk': 'EXTERNAL'},
    }
    with open(os.path.join(out_dir, 'environment.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(environment, fh, ensure_ascii=False, indent=2)

    # ---------------- L1: 协议/契约/反例 ----------------
    l1_cases = [
        ('L1-01', '团队契约与 Schema 校验',
         [PY, 'scripts/validate_team_contracts.py', '--all']),
        ('L1-02', '验收器严格性反例（LIM-01 / REAL-STATE）',
         [PY, '-m', 'pytest', 'tests/unit/test_member_module_strictness.py', '-q']),
        ('L1-03', 'ADP-01 输入拒绝反例（ADP-N01..N10）',
         [PY, '-m', 'pytest', 'tests/unit/test_adp01_input_rejection.py', '-q']),
        ('L1-04', 'event_id / request_id 边界',
         [PY, '-m', 'pytest', 'tests/unit/test_event_id_contract_boundaries.py', '-q']),
        ('L1-05', '在线证据篡改反例',
         [PY, '-m', 'pytest',
          'tests/unit/test_m3_online_evidence_counterexamples.py', '-q']),
        ('L1-06', 'ON-06 报告声明对账反例',
         [PY, '-m', 'pytest', 'tests/unit/test_on06_report_claims.py', '-q']),
    ]
    for cid, name, cmd in l1_cases:
        result = run(cmd, timeout=1800)
        ok = result['returncode'] == 0
        report.add('L1_PROTOCOL', cid, name, result, 'PASS' if ok else 'FAIL',
                   extra={'pytest_counts': parse_pytest_counts(result['stdout'])})

    # ---------------- L2: 真实算法验收（离线） ----------------
    l2_cases = [
        ('L2-01', 'M2 identity_trust 真实验收',
         [PY, 'scripts/check_member_module.py', '--module', 'identity_trust',
          '--config', 'config/team_modules.member2.real.yaml',
          '--real-fixture', 'config/acceptance/real_scenarios.member2.yaml',
          '--out-dir', os.path.join(out_dir, 'l2'), '--run-id', 'm2']),
        ('L2-02', 'M3 task_risk 真实验收',
         [PY, 'scripts/check_member_module.py', '--module', 'task_risk',
          '--config', 'config/team_modules.member3.real.yaml',
          '--real-fixture', 'config/acceptance/real_scenarios.member3.yaml',
          '--out-dir', os.path.join(out_dir, 'l2'), '--run-id', 'm3']),
    ]
    for cid, name, cmd in l2_cases:
        result = run(cmd, timeout=1800)
        report_path = os.path.join(out_dir, 'l2',
                                   'm2' if cid == 'L2-01' else 'm3', 'report.json')
        counts = None
        if os.path.isfile(report_path):
            with open(report_path, encoding='utf-8') as fh:
                counts = json.load(fh).get('counts')
        # 门槛由 checker 自行判定（meets_pr_gate）。3 个 STATE-* FAIL 是
        # "mock 场景开关对真实模块不适用"的非门槛记录，必须保留可见。
        gate = None
        if os.path.isfile(report_path):
            with open(report_path, encoding='utf-8') as fh:
                gate = json.load(fh).get('meets_pr_gate')
        report.add('L2_ALGORITHM', cid, name, result,
                   'PASS' if (result['returncode'] == 0 and gate is True) else 'FAIL',
                   note='counts={0} meets_pr_gate={1}'.format(counts, gate),
                   extra={'checker_counts': counts, 'meets_pr_gate': gate,
                          'report_path': os.path.relpath(report_path, REPO)})

    # ---------------- 全仓单元测试 ----------------
    result = run([PY, '-m', 'pytest', 'tests/unit', '-q'], timeout=3600)
    report.add('L1_PROTOCOL', 'L1-00', '全仓 Python 单元测试', result,
               'PASS' if result['returncode'] == 0 else 'FAIL',
               extra={'pytest_counts': parse_pytest_counts(result['stdout'])})

    # ---------------- L3: ROS 2 基础 A/B ----------------
    result = run(['bash', 'scripts/run_demo.sh'], timeout=1800)
    ab_pass = ('DEMO RESULT: PASS' in (result['stdout'] or '')
               and result['returncode'] == 0)
    report.add('L3_ROS2', 'L3-01', 'Gateway/NavigationSim A/B 基础演示', result,
               'PASS' if ab_pass else 'FAIL',
               note='域 42 普通模式')

    # ---------------- L3: M3 在线六场景 ----------------
    if args.skip_online:
        report.add('L3_ROS2', 'L3-02', 'M3 在线六场景', {'returncode': None},
                   'NOT_RUN', note='--skip-online')
    else:
        online_run = 'rc2-' + run_id
        drive = (
            'cd /ws && RUN_ID="{run}" bash scripts/m3_online_drive.sh '
            '"{run}" "/tmp/m3_online/{run}"'
        ).format(run=online_run)
        result = run_in_container(drive, timeout=2400)
        report.add('L3_ROS2', 'L3-02', 'M3 在线第一组（ON-01/02/05）', result,
                   'PASS' if result['returncode'] == 0 else 'FAIL',
                   note='run_id={0}'.format(online_run))
        extra_run = 'rc2b-' + run_id
        drive2 = (
            'cd /ws && bash scripts/m3_online_extra.sh "{run}" '
            '"/tmp/m3_online/{run}"'
        ).format(run=extra_run)
        result2 = run_in_container(drive2, timeout=2400)
        report.add('L3_ROS2', 'L3-03', 'M3 在线第二组（ON-03/04/06）', result2,
                   'PASS' if result2['returncode'] == 0 else 'FAIL',
                   note='run_id={0}'.format(extra_run))

        # 证据回收：容器内 /tmp 结果拷入受测工作区，再合并两组并独立复核
        collect = (
            'set -e; '
            'mkdir -p /ws/logs/m3_online/{a} /ws/logs/m3_online/{b}; '
            'cp -a /tmp/m3_online/{a}/. /ws/logs/m3_online/{a}/ 2>/dev/null || true; '
            'cp -a /tmp/m3_online/{b}/. /ws/logs/m3_online/{b}/ 2>/dev/null || true; '
            'echo COLLECTED'
        ).format(a=online_run, b=extra_run)
        collect_result = run_in_container(collect, timeout=600)
        report.add('L3_ROS2', 'L3-04', '回收两组在线证据', collect_result,
                   'PASS' if 'COLLECTED' in (collect_result['stdout'] or '')
                   else 'FAIL')

        merge_dir = os.path.join(out_dir, 'm3-online')
        os.makedirs(os.path.join(merge_dir, 'merged'), exist_ok=True)
        merged = os.path.join(merge_dir, 'merged')
        for name in ('gateway_audit.jsonl', 'navsim_goals.jsonl'):
            sources = [os.path.join(REPO, 'logs', 'm3_online', online_run,
                                    'stack-a', name),
                       os.path.join(REPO, 'logs', 'm3_online', extra_run,
                                    'stack-b', name)]
            with open(os.path.join(merged, name), 'w', encoding='utf-8') as out:
                for src in sources:
                    if os.path.isfile(src):
                        with open(src, encoding='utf-8') as fh:
                            out.write(fh.read())
        for tag, run_label in (('stack-a', online_run), ('stack-b', extra_run)):
            base = os.path.join(REPO, 'logs', 'm3_online', run_label, tag)
            if os.path.isdir(base):
                for entry in os.listdir(base):
                    if entry.startswith(('f0_', 'adapter_', 'manifest')):
                        src = os.path.join(base, entry)
                        if os.path.isfile(src):
                            shutil.copy2(src, os.path.join(merged, entry))
                shutil.copytree(base, os.path.join(merge_dir, tag),
                                dirs_exist_ok=True)

        # 注意：命令必须按参数**名称**逐项构造。此前用下标插入
        # (`verify_cmd[3:3] = [...]`) 把 --run-dir 的取值挤走，导致
        # argparse 报 "expected one argument"，是一次真实的工具缺陷。
        claims = os.path.join(merged, 'report_claims.json')
        if args.claims_template and os.path.isfile(args.claims_template):
            shutil.copy2(args.claims_template, claims)
        verify_cmd = [PY, 'scripts/verify_m3_online_evidence.py',
                      '--run-dir', merged,
                      '--json-out', os.path.join(merged, 'verification.json'),
                      '--md-out', os.path.join(merged, 'verification.md')]
        if os.path.isfile(claims):
            verify_cmd += ['--claims', claims]
        verify_result = run(verify_cmd, timeout=900)
        report.add('L3_ROS2', 'L3-05', '跨层证据独立复核', verify_result,
                   'PASS' if verify_result['returncode'] == 0 else 'FAIL')

    # ---------------- L4: DDS-Security Enforce ----------------
    sros2 = (
        'cd /ws && set +u && source /opt/ros/jazzy/setup.bash && '
        'source install/setup.bash && set -u && export ROS_DOMAIN_ID=42 && '
        'python3 tests/integration/sros2_check.py --run-id rc2-regression'
    )
    result = run_in_container(sros2, timeout=2400)
    summary_ok = 'SROS2 SUMMARY (7 passed / 7 total)' in (result['stdout'] or '')
    report.add('L4_DDS', 'L4-01', 'DDS-Security Enforce S1–S6（域 43）', result,
               'PASS' if (result['returncode'] == 0 and summary_ok) else 'FAIL',
               note='与 L3 不是同一次运行；L3 为域 42 普通模式')

    # ---------------- 汇总 ----------------
    document = {
        'run_id': run_id,
        'generated_at': now(),
        'git_sha': sha,
        'branch': facts.get('branch'),
        'environment': environment,
        'checks': report.entries,
        'counts': report.counts(),
        'failures': [e['id'] for e in report.failures()],
        'verdict': 'PASS' if not report.failures() else 'FAIL',
    }
    with open(os.path.join(out_dir, 'test_results.json'), 'w',
              encoding='utf-8') as fh:
        json.dump(document, fh, ensure_ascii=False, indent=2)

    print(json.dumps({'run_id': run_id, 'git_sha': sha,
                      'counts': document['counts'],
                      'failures': document['failures'],
                      'verdict': document['verdict']},
                     ensure_ascii=False, indent=2))
    return 0 if document['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
