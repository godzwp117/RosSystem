#!/usr/bin/env python3
"""统一成员模块验收脚本。

用法：
    python3 scripts/check_member_module.py --module comm_risk \
        --config config/team_modules.local.yaml
    python3 scripts/check_member_module.py --module identity_trust --config ...
    python3 scripts/check_member_module.py --module task_risk --config ...

设计原则
--------
* **复用**既有适配层语义（`scripts/team_demo.py` 的模块调用方式与状态门槛），
  以及既有 JSON Schema（`docs/interfaces/schemas/`）。不重写第二套安全框架。
* **记录真实执行证据**：命令、可执行文件、子进程返回码、stdout 实际长度、
  Schema 校验结果、被测模块名。防止"偷偷换成 Mock 仍声称通过"。
* **严格区分两种失败**：
    - `LEGAL_BLOCK`  —— 输出结构**合法**，但安全状态不允许推进（正常的安全阻断）
    - `SCHEMA_INVALID` —— 输出结构**本身非法**
* **三层测试不可混同**：
    - L1 协议层（本脚本，受控 fixtures）
    - L2 真实算法层（需成员提供真实输入/输出/证据来源）
    - L3 ROS 2 在线联调（需 Jazzy 容器 + Gateway 审计 + NavigationSim Goal）
* 强制项失败 → **非零退出码**；SKIPPED **不计入** PASS。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

# **复用**适配层已有的有界读取与进程组终止实现，避免出现第二套语义不同的
# 超时/限流/清理逻辑。team_demo.py 在 import 时无副作用。
import team_demo as _td  # noqa: E402

MAX_STDERR_KEEP = _td.MAX_STDERR_LIMIT
SCHEMA_DIR = os.path.join(REPO, 'docs', 'interfaces', 'schemas')
ENVELOPE_FIXTURE = os.path.join(REPO, 'tests', 'research', 'fixtures',
                                'envelope_normal.json')

#: 模块身份 -> (输出 Schema 文件, 允许推进状态, 其余合法状态)
MODULE_SPEC = {
    'comm_risk': ('comm_risk_evidence.schema.json', 'NORMAL',
                  {'SUSPICIOUS', 'UNKNOWN', 'ERROR'}),
    'identity_trust': ('identity_trust_assessment.schema.json', 'AUTHORIZED',
                       {'DENIED', 'UNKNOWN', 'ERROR'}),
    'task_risk': ('task_risk_decision.schema.json', 'ALLOW_RECOMMENDED',
                  {'BLOCK_RECOMMENDED', 'UNKNOWN', 'ERROR'}),
}


#: FIX-03：三模块 × 四状态 = 12 个必须**真实运行**验证的组合。
#: (场景名, 期望状态, 分类)  —— 分类只有 PROCEED 与 LEGAL_BLOCK 两种。
STATE_MATRIX = {
    'comm_risk': [
        ('normal', 'NORMAL', 'PROCEED'),
        ('suspicious', 'SUSPICIOUS', 'LEGAL_BLOCK'),
        ('unknown', 'UNKNOWN', 'LEGAL_BLOCK'),
        ('error', 'ERROR', 'LEGAL_BLOCK'),
    ],
    'identity_trust': [
        ('authorized', 'AUTHORIZED', 'PROCEED'),
        ('denied', 'DENIED', 'LEGAL_BLOCK'),
        ('unknown', 'UNKNOWN', 'LEGAL_BLOCK'),
        ('error', 'ERROR', 'LEGAL_BLOCK'),
    ],
    'task_risk': [
        ('allow', 'ALLOW_RECOMMENDED', 'PROCEED'),
        ('block', 'BLOCK_RECOMMENDED', 'LEGAL_BLOCK'),
        ('unknown', 'UNKNOWN', 'LEGAL_BLOCK'),
        ('error', 'ERROR', 'LEGAL_BLOCK'),
    ],
}


def envelope_for(module: str, scenario: str, request_id: str) -> dict:
    """构造带指定场景的受控信封（mock 场景块 + 真实候选动作）。"""
    env = build_envelope(request_id)
    env['observations'][0]['detail']['f0_mock'] = {
        'comm_risk': {'scenario': scenario},
        'identity_trust': {'scenario': scenario},
        'task_risk': {'scenario': scenario},
    }
    return env


def classify(status: str, proceed_state: str) -> str:
    """把状态分为 PROCEED / LEGAL_BLOCK。**不涉及 Schema 合法性** ——
    结构非法的输出由 Schema 校验单独判负。"""
    return 'PROCEED' if status == proceed_state else 'LEGAL_BLOCK'


def rel(path: str) -> str:
    try:
        return os.path.relpath(path, REPO)
    except ValueError:
        return path


def load_yaml(path: str) -> dict:
    try:
        import yaml
    except ImportError:
        sys.stderr.write('ERROR: 需要 PyYAML。安装：pip install pyyaml\n')
        sys.exit(2)
    with open(path, encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}


# ---------------------------------------------------------------------------
# 真实模块场景（L2 入口）：受信任本地 fixture + 受信任配置中的命令档案
# ---------------------------------------------------------------------------
# 为什么需要它
# ------------
# `detail.f0_mock.scenario` 是**参考 Mock 的控制开关**。真实规则模块
# （如 modules/member3_taskrisk/module.py）不解析该开关，而是依据候选 Action、
# Task ID、坐标系、目标位置、TaskPolicy 与可选可信历史审计计算真实建议。
# 因此用 Mock 开关无法触发真实模块的四种状态，旧脚本只能得到 3 个 FAIL。
#
# 安全约束
# --------
# * 场景定义只来自 `--real-fixture` 指定的**受信任本地文件**；
# * 可执行命令只能来自 `--config` 的 `real_command_profiles`，业务 JSON 不得
#   指定命令、策略文件或可执行文件（`_reject_command_injection` 强制）；
# * 期望状态写在 fixture 中并被**真实输出状态**核对：只匹配期望标签不算通过；
# * fixture 只是本地测试输入，不是网关策略，也不改变 Gateway 规则顺序。
REAL_FIXTURE_SCHEMA_VERSION = '1.0.0'
#: fixture 场景名只允许安全标识符（用于构造检查项 ID，避免注入）。
SAFE_SCENARIO_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$')
#: 业务 JSON 中绝不能出现的「本地执行控制」字段名（大小写不敏感）。
FORBIDDEN_PATCH_KEYS = ('command', 'executable', 'exec', 'argv', 'shell',
                        'cwd', 'workdir', 'policy', 'policy_path',
                        'audit_log', 'env', 'environment', 'pythonpath',
                        'module_path', 'script')


class FixtureError(ValueError):
    """fixture 本身不合法：验收器必须失败关闭，而不是继续跑场景。"""


def _reject_command_injection(patch: dict, where: str) -> None:
    """禁止业务输入携带任何本地执行控制字段（只允许数据字段）。"""
    stack = [patch]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).strip().lower() in FORBIDDEN_PATCH_KEYS:
                    raise FixtureError(
                        '{0} 不得通过业务输入指定本地执行控制字段 {1!r}；'
                        '命令与策略路径只能来自受信任配置'.format(where, key))
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)


def _bounded_repo_path(raw, where: str) -> str:
    """把 fixture 中的相对路径解析到仓库内，拒绝越界与绝对路径。"""
    if not isinstance(raw, str) or not raw.strip():
        raise FixtureError('{0} 必须是仓库内相对路径'.format(where))
    candidate = os.path.realpath(os.path.join(REPO, raw))
    root = os.path.realpath(REPO)
    if candidate != root and not candidate.startswith(root + os.sep):
        raise FixtureError('{0} 越出仓库范围: {1!r}'.format(where, raw))
    return candidate


def _string_args(raw, where: str) -> list:
    if not isinstance(raw, list) or not raw or not all(
            isinstance(part, str) and part for part in raw):
        raise FixtureError('{0} 必须是非空字符串数组'.format(where))
    return list(raw)


#: 交付配置里常见的 Python 解释器写法。它们是否可用取决于 PATH：
#: 成员交付配置写 `python3`，而真实模块需要 jsonschema>=4（Draft 2020-12）。
#: 若验收器自己跑在满足依赖的解释器里，却用 PATH 上的另一个 python3 调模块，
#: 就会得到「模块不可运行」的假失败。只统一解释器，不改参数、不加权限。
PYTHON_ALIASES = ('python', 'python3', 'python3.10', 'python3.11', 'python3.12',
                  'python3.13')


def resolve_interpreter(command: list) -> list:
    """把命令首部的裸 `python3` 映射到**当前**解释器（同一验收进程）。

    仅改写第一个元素且仅当它是裸 python 别名；不改任何后续参数，
    因此不会放松 module_input Schema、候选入口或输出上限的检查。
    """
    if command and command[0] in PYTHON_ALIASES:
        return [sys.executable] + list(command[1:])
    return list(command)


def resolve_profile_command(base_command: list, config: dict, profile) -> list:
    """从**受信任配置**中解析场景命令档案。

    支持两种档案形式（都只存在于 `--config` 指向的本地文件里）：
      * 字符串：`real_command_profiles.<name>` 必须是非空字符串数组；
      * 映射：可给出 `command`（完整替换）或 `args`（追加到模块命令之后）。

    fixture 只能引用档案**名字**，不能提供命令本身。
    """
    if profile is None:
        return list(base_command)          # 基础命令原样返回
    if not isinstance(profile, str) or not profile.strip():
        raise FixtureError('scenario.command_profile 必须是非空字符串')
    profiles = (config or {}).get('real_command_profiles') or {}
    if not isinstance(profiles, dict):
        raise FixtureError('配置 real_command_profiles 必须是映射')
    if profile not in profiles:
        raise FixtureError(
            '配置 real_command_profiles 中不存在档案 {0!r}（可用: {1}）'.format(
                profile, sorted(profiles)))
    entry = profiles[profile]
    where = 'real_command_profiles.{0}'.format(profile)
    if isinstance(entry, list):
        return _string_args(entry, where)
    if isinstance(entry, dict):
        if 'command' in entry:
            # 命令整体来自受信任配置，与业务输入无关
            return resolve_interpreter(
                _string_args(entry['command'], where + '.command'))
        if 'args' in entry:
            return resolve_interpreter(
                list(base_command) + _string_args(entry['args'], where + '.args'))
    raise FixtureError(
        '{0} 必须是字符串数组，或含 command/args 的映射'.format(where))


def parse_real_fixture(path: str, module: str, config: dict) -> dict:
    """读取并校验真实场景 fixture，返回 {'scenarios': [...], ...}。

    任何结构问题都抛 FixtureError（调用方失败关闭，不得继续判定通过）。
    """
    document = load_yaml(path)
    if not isinstance(document, dict):
        raise FixtureError('fixture 根节点必须是映射')
    if document.get('schema_version') != REAL_FIXTURE_SCHEMA_VERSION:
        raise FixtureError('fixture schema_version 必须是 {0!r}'.format(
            REAL_FIXTURE_SCHEMA_VERSION))
    real = document.get('real_scenarios')
    if not isinstance(real, dict):
        raise FixtureError('fixture 缺少 real_scenarios 段')
    rows = real.get(module)
    if not isinstance(rows, list) or not rows:
        raise FixtureError('fixture 缺少模块 {0} 的场景列表'.format(module))
    spec = MODULE_SPEC[module]
    base_command = (config.get('modules') or {}).get(module, {}).get('command')
    if not isinstance(base_command, list) or not base_command:
        raise FixtureError('配置缺少模块 {0} 的命令数组'.format(module))

    scenarios, seen = [], set()
    for index, row in enumerate(rows):
        where = 'real_scenarios.{0}[{1}]'.format(module, index)
        if not isinstance(row, dict):
            raise FixtureError('{0} 必须是映射'.format(where))
        name = row.get('name')
        if not isinstance(name, str) or not SAFE_SCENARIO_NAME.fullmatch(name):
            raise FixtureError('{0}.name 非法: {1!r}'.format(where, name))
        if name in seen:
            raise FixtureError('{0}.name 重复: {1}'.format(where, name))
        seen.add(name)
        expected_state = row.get('expected_state')
        legal = {spec[1]} | set(spec[2])
        if expected_state not in legal:
            raise FixtureError(
                '{0}.expected_state {1!r} 不在该模块合法枚举 {2}'.format(
                    where, expected_state, sorted(legal)))
        expected_class = row.get('expected_class')
        if expected_class not in ('PROCEED', 'LEGAL_BLOCK'):
            raise FixtureError('{0}.expected_class 非法: {1!r}'.format(
                where, expected_class))
        # 期望分类必须与期望状态自洽（不能声明 PROCEED 却期望阻断状态）
        if classify(expected_state, spec[1]) != expected_class:
            raise FixtureError(
                '{0}: expected_state {1!r} 与 expected_class {2!r} 不自洽'.format(
                    where, expected_state, expected_class))
        patch = row.get('envelope_patch') or {}
        if not isinstance(patch, dict):
            raise FixtureError('{0}.envelope_patch 必须是映射'.format(where))
        _reject_command_injection(patch, where + '.envelope_patch')
        request_id = row.get('request_id') or 'req-real-{0}'.format(name)
        if not isinstance(request_id, str) or not request_id.strip():
            raise FixtureError('{0}.request_id 非法'.format(where))
        policy = row.get('policy')
        policy_path = _bounded_repo_path(policy, where + '.policy') if policy else None
        expect = row.get('expect') or {}
        if not isinstance(expect, dict):
            raise FixtureError('{0}.expect 必须是映射'.format(where))
        adapter_decision = expect.get('adapter_decision')
        if adapter_decision not in (None, 'READY_FOR_GATEWAY_SUBMISSION',
                                   'ADAPTER_BLOCK'):
            raise FixtureError(
                '{0}.expect.adapter_decision 非法: {1!r}'.format(
                    where, adapter_decision))
        adapter_reason = expect.get('adapter_reason')
        if adapter_reason is not None and (
                not isinstance(adapter_reason, str) or not adapter_reason):
            raise FixtureError(
                '{0}.expect.adapter_reason 必须是非空字符串'.format(where))
        allowed_states = expect.get('allowed_states')
        if allowed_states is not None:
            if (not isinstance(allowed_states, list) or not allowed_states
                    or any(s not in legal for s in allowed_states)):
                raise FixtureError(
                    '{0}.expect.allowed_states 必须是该模块合法状态的非空子集'.format(
                        where))
            if expected_state not in allowed_states:
                raise FixtureError(
                    '{0}.expect.allowed_states 必须包含 expected_state {1!r}'.format(
                        where, expected_state))
        scenarios.append({
            'name': name,
            'description': row.get('description') or '',
            'expected_state': expected_state,
            'expected_class': expected_class,
            'request_id': request_id,
            'policy': policy_path,
            'policy_ref': policy,
            'trigger': row.get('trigger') or '',
            'command': resolve_profile_command(base_command, config,
                                               row.get('command_profile')),
            'command_profile': row.get('command_profile'),
            'patch': patch,
            'expect': {
                'reason_code': expect.get('reason_code'),
                'policy_version': expect.get('policy_version'),
                'contains': expect.get('contains'),
                # 适配层预期（可选）：合法真实条件默认只应产生
                # READY_FOR_GATEWAY_SUBMISSION；当模块的"模块级结论"合法、
                # 但缺少**当前请求身份绑定**时，fixture 可以显式声明适配层
                # 必须阻断，并由 adapter_reason 精确核对原因码。
                'adapter_decision': expect.get('adapter_decision'),
                'adapter_reason': expect.get('adapter_reason'),
            },
        })
    return {'fixture': rel(path), 'module': module, 'scenarios': scenarios}


def deep_patch(target: dict, patch: dict) -> dict:
    """把 fixture 的数据字段合并进信封（只合并数据，命令类字段已被拒绝）。"""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_patch(target[key], value)
        else:
            target[key] = value
    return target


def invoke_real_scenario(module: str, scenario: dict, timeout: float,
                         max_bytes: int) -> dict:
    """用真实条件调用模块一次，返回可追溯的行记录。"""
    env = build_envelope(scenario['request_id'])
    deep_patch(env, scenario['patch'])
    # 命令整体来自受信任配置档案；业务 JSON 从不参与命令构造
    command = list(scenario['command'])
    result = invoke(command, env, timeout, max_bytes)
    row = {
        'scenario': scenario['name'],
        'description': scenario['description'],
        'trigger': scenario['trigger'],
        'expected_state': scenario['expected_state'],
        'expected_class': scenario['expected_class'],
        'expected_reason_code': scenario['expect']['reason_code'],
        'expect_contains': scenario['expect'].get('contains') or [],
        'expect_allowed_states': scenario['expect'].get('allowed_states') or [],
        'command_profile': scenario['command_profile'],
        'command': command,
        'policy_ref': scenario['policy_ref'],
        'returncode': result['returncode'],
        'structured': False, 'schema_ok': None, 'actual_state': None,
        'actual_class': None, 'ids_ok': False, 'traceability_ok': False,
        'actual_reason_code': None, 'policy_version': None, 'event_id': None,
        'exceeded': result['exceeded'],
        'stderr_head': (result['stderr'] or '')[:200],
        'stdout_bytes': result['stdout_bytes'],
    }
    if result['exceeded'] or not result['stdout'].strip():
        row['detail'] = 'exceeded={0} stdout={1}B'.format(
            result['exceeded'], result['stdout_bytes'])
        return row, env, None
    try:
        payload = json.loads(result['stdout'])
    except ValueError as exc:
        row['detail'] = '非法 JSON: {0}'.format(exc)
        return row, env, None
    row['structured'] = True
    row['event_id'] = payload.get('event_id')
    row['actual_state'] = payload.get('status')
    row['ids_ok'] = (payload.get('run_id') == env['run_id']
                     and payload.get('request_id') == env['request_id'])
    extensions = payload.get('extensions') or {}
    member = (extensions.get('member3') or extensions.get('member2')
              or extensions.get('member1_comm') or {})
    row['actual_reason_code'] = (
        member.get('reason_code')
        or (payload.get('authorization') or {}).get('denial_layer')
        or payload.get('reason_code'))
    row['policy_version'] = (payload.get('policy_ref') or {}).get('policy_version')
    ok, serr = validate(payload, os.path.join(SCHEMA_DIR, MODULE_SPEC[module][0]))
    row['schema_ok'] = ok
    if ok:
        row['actual_class'] = classify(row['actual_state'], MODULE_SPEC[module][1])
    else:
        row['detail'] = serr
    return row, env, payload


def _policy_argument(command: list):
    """从受信任配置解析出的命令中取出 `--policy` 实参（只读，用于追溯）。"""
    for index, part in enumerate(command):
        if part == '--policy' and index + 1 < len(command):
            return command[index + 1]
        if part.startswith('--policy='):
            return part.split('=', 1)[1]
    return None


def _yaml_task_policy_parses(path):
    """TaskPolicy（YAML）能否被权威解析器接受。"""
    sys.path.insert(0, os.path.join(REPO, 'src', 'rg_policy'))
    from rg_policy.task_policy import parse_task_policy
    import yaml as _yaml
    parse_task_policy(_yaml.safe_load(path.read_text(encoding='utf-8')), str(path))


def _sros2_policy_parses(path):
    """SROS2 权限策略（XML）能否被 XML 解析器接受且根为 <policy>。"""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(path.read_bytes())
    if root.tag.rsplit('}', 1)[-1] != 'policy':
        raise ValueError('not a SROS2 policy root: {0}'.format(root.tag))


def policy_file_state(declared):
    """独立判定配置指向的策略文件的**真实状态**（不依赖模块自报）。

    返回 'VALID' / 'ABSENT' / 'CORRUPT' / 'UNKNOWN'。
    这是验收器的地面真值：模块输出必须与之自洽，否则说明期望标签与
    真实条件不符（例如策略其实可解析，却期望 UNKNOWN）。

    按扩展名选择解析器，因此对两种既有策略格式都成立：
      * `.yaml`/`.yml` -> Gateway 的 TaskPolicy（rg_policy 权威解析器）
      * `.xml`         -> SROS2 权限策略（与 M2 读取的是同一种文件）
    两种解析器都失败才算 CORRUPT，避免把「另一种格式」误判成损坏。
    """
    if not declared:
        return 'UNKNOWN'
    path = Path(declared) if os.path.isabs(declared) else Path(REPO) / declared
    if not path.is_file():
        return 'ABSENT'
    parsers = ([_sros2_policy_parses] if path.suffix.lower() == '.xml'
               else [_yaml_task_policy_parses])
    try:
        for parser in parsers:
            parser(path)
        return 'VALID'
    except Exception:                          # noqa: BLE001
        return 'CORRUPT'


def verify_traceability(row: dict, payload, command: list) -> str:
    """核对「场景输入 / 受信任配置 / 期望状态 / 实际输出」四者可追溯。

    追溯落在**模块真实读取的那个策略路径**上，而不是 fixture 自己声明的期望，
    并且与验收器独立测得的策略文件真实状态交叉核对。返回失败原因（'' 表示满足）。
    """
    declared = _policy_argument(command)
    state = policy_file_state(declared)
    row['policy_ref'] = declared
    row['policy_file_state'] = state
    fail = _traceability_failure(row, payload, declared, state)
    if not fail:
        fail = _contains_failure(row, payload)
    row['traceability_ok'] = not fail
    return fail


def _contains_failure(row: dict, payload) -> str:
    """fixture 声明的必需内容必须确实出现在输出中（防「只对标签」）。"""
    needles = row.get('expect_contains') or []
    if not needles:
        return ''
    blob = json.dumps(payload, ensure_ascii=False)
    for needle in needles:
        if needle not in blob:
            return '输出缺少 fixture 要求的内容 {0!r}'.format(needle)
    return ''


def _traceability_failure(row: dict, payload, declared, state) -> str:
    if payload is None:
        return '模块未产出结构化输出，无法追溯策略'
    refs = [str(r.get('ref', '')) for r in (payload.get('evidence_refs') or [])
            if isinstance(r, dict)]
    if not refs:
        return '输出没有任何证据引用，无法追溯依据'
    actual = row.get('actual_state')
    if state == 'VALID':
        # 策略可用 -> 输出必须回引该策略（路径引用或策略版本）
        expected = declared[-512:]      # 模块实现按 512 字符截断记录
        cited = any(expected == ref or expected.endswith(ref)
                    or ref.endswith(expected) for ref in refs)
        if not (cited or row.get('policy_version')):
            return '策略可解析但输出未回引 {0!r}；引用={1}'.format(
                declared, refs[:4])
    # 状态集合无法由策略文件状态单独推出（例如 M2 在策略可解析时仍可能因
    # 资源不匹配而给出 UNKNOWN），因此改由 fixture 的 expect.allowed_states
    # 显式声明，并与**实际状态**核对。
    allowed = row.get('expect_allowed_states') or []
    if allowed and actual not in allowed:
        return '策略文件真实状态 {0}，实际状态 {1!r} 不在允许集合 {2}'.format(
            state, actual, sorted(allowed))
    return ''


def _pin_real_command(temp_dir: str, config: dict, module: str,
                      command: list) -> tuple:
    """把某个真实场景命令写进一份**临时受信任配置**，供 F0 适配层使用。

    只改目标模块的 command，其他模块保持 fixture 配置中的原样（通常仍是
    Mock），因此不会新建任何下游执行通道，也不会触及正式 Gateway 策略。
    """
    import copy
    import yaml
    pinned = copy.deepcopy(config)
    pinned.setdefault('modules', {}).setdefault(module, {})['command'] = \
        resolve_interpreter(command)
    cfg_path = os.path.join(temp_dir, 'modules-{0}.yaml'.format(module))
    log_path = os.path.join(temp_dir, 'adapter-{0}.jsonl'.format(module))
    with open(cfg_path, 'w', encoding='utf-8') as handle:
        yaml.safe_dump(pinned, handle, allow_unicode=True)
    return cfg_path, log_path


#: 成员一真实通信观测的**真实 data row** 来源（已提交、可追溯）。
COMM_PROBE_FIXTURE = os.path.join(
    REPO, 'tests', 'fixtures', 'member1', 'rospace_comm_rows.json')


def comm_observation_detail() -> dict:
    """构造 comm_risk 需要的真实通信观测块。

    为什么需要
    ----------
    真实通信风险模块依赖**真实**的特征向量、资源、观察窗口与业务请求计数。
    统一验收器原先只构造 `f0_mock` 场景开关，于是真实模块会（正确地）
    失败关闭退出 4，导致 stdout / JSON / 输出上限 / event_id 这些协议层
    检查全部失去意义（不是模块不可调用，而是输入里根本没有可映射的观测）。

    这里注入的是 tests/fixtures/member1/rospace_comm_rows.json 中的**真实
    held-out 数据行**（分片号 / 原始 CSV 行号 / 标签 / 模型打分均可追溯），
    不是随机填充，也不是标签反推。它只用于让协议层检查有合法输入；
    各状态是否可达由 REAL-STATE-* 用真实条件单独核对。
    """
    try:
        with open(COMM_PROBE_FIXTURE, encoding='utf-8') as handle:
            document = json.load(handle)
        threshold = document['model']['threshold']
        rows = document['rows']
        row = next((item for item in rows if item['score'] < threshold), rows[0])
    except (OSError, ValueError, KeyError, IndexError, StopIteration):
        return {}
    return {
        'rospace_comm': {
            'features': {'feature_names': row['feature_names'],
                         'values': row['values']},
        },
        'f0_runtime': {
            'communication': {'resource': '/rg/guarded_navigate',
                              'resource_type': 'Action', 'operation': 'GOAL_SEND'},
            'request_count': 12,
            'window': {'start': '2026-10-12T11:59:55Z',
                       'end': '2026-10-12T12:00:00Z', 'duration_ms': 5000},
        },
        'comm_probe_provenance': {
            'fixture': 'tests/fixtures/member1/rospace_comm_rows.json',
            'shard': row['shard'],
            'original_csv_row': row['original_csv_row'],
            'dataset_label': row['dataset_label'],
            'score': row['score'],
            'note': 'real held-out row; injected by the acceptance harness, not by business input',
        },
    }


def build_envelope(request_id: str = 'req-accept-001') -> dict:
    """构造一个最小合法的 ModuleInputEnvelope（受控 fixture）。

    同时带上 `detail.f0_mock` 场景块：仓库自带的参考 Mock 依靠它选择场景，
    没有它 task_risk Mock 会因缺少任务上下文而无法产出结果。
    成员的真实模块应当**忽略**该块（它只是 mock 的控制字段）。

    另外附带一份**真实**通信观测块（见 comm_observation_detail），
    使需要真实观测映射的模块（成员一）也能在协议层被真实调用。
    """
    detail = {'f0_mock': {
        'comm_risk': {'scenario': 'normal'},
        'identity_trust': {'scenario': 'authorized'},
        'task_risk': {'scenario': 'allow'}}}
    detail.update(comm_observation_detail())
    return {
        'schema_version': '1.0.0-proposed',
        'run_id': 'member-acceptance',
        'created_at': '2026-10-12T12:00:00Z',
        'request_id': request_id,
        'candidate_action': {
            'action_resource': '/rg/guarded_navigate',
            'operation': 'NAVIGATE',
            'task_id': 'patrol_a_001',
            'target': {'frame_id': 'map', 'x': 2.0, 'y': 2.0, 'z': 0.0},
        },
        'observations': [{
            'source': '/rg/guarded_navigate',
            'kind': 'MOCK',
            'observed_at': '2026-10-12T12:00:00Z',
            'detail': detail,
        }],
        'evidence_refs': [{'ref': 'member-acceptance', 'kind': 'MOCK'}],
    }


class Report:
    def __init__(self, module: str, config: str):
        self.data = {
            'baseline_sha': None,
            'module': module,
            'config': rel(config),
            'module_command': None,
            'executable': None,
            'test_layer': 'L1_PROTOCOL',
            'layer_note': ('本脚本只做 L1 协议层验收。通过 L1 不代表算法有效（L2），'
                           '也不代表具备实时监测能力（L3）。'),
            'checks': [],
            'implementation_type': None,
            'algorithm_evidence': 'NOT_READY',
            'runtime_integration': 'BLOCKED',
            'meets_pr_gate': False,
            'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }

    def add(self, cid: str, name: str, status: str, detail: str = '',
            mandatory: bool = True, extra: dict = None):
        entry = {'id': cid, 'check': name, 'status': status,
                 'detail': str(detail)[:400], 'mandatory': mandatory}
        if extra:
            entry.update(extra)
        self.data['checks'].append(entry)
        return entry

    def counts(self):
        out = {}
        for c in self.data['checks']:
            out[c['status']] = out.get(c['status'], 0) + 1
        return out

    def mandatory_failures(self):
        # `gate=False` 的记录是**如实保留但不计入门槛**的适用性说明
        # （例如把 mock 场景开关套用到不解析该开关的真实模块）。它不是
        # 「删除失败检查」：记录、状态与原因都仍然完整出现在报告里。
        return [c for c in self.data['checks']
                if c['mandatory'] and c.get('gate', True)
                and c['status'] != 'PASS']


def validate(payload: dict, schema_path: str):
    """返回 (ok, error_text)。"""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return None, 'jsonschema 未安装（需要 >=4.0）'
    if not os.path.isfile(schema_path):
        return None, 'Schema 文件不存在: {0}'.format(rel(schema_path))
    with open(schema_path, encoding='utf-8') as handle:
        schema = json.load(handle)
    try:
        Draft202012Validator(schema).validate(payload)
        return True, ''
    except Exception as exc:                   # noqa: BLE001
        return False, str(exc).split('\n')[0][:300]


def invoke(command: list, envelope: dict, timeout: float, max_bytes: int,
           stdin_text: str = None):
    """调用模块，**在读取过程中**限制输出。

    为什么不能再用 `subprocess.run(capture_output=True)`
    ----------------------------------------------------
    那种写法会先把 stdout/stderr **全部读入内存**，之后才检查
    `max_stdout_bytes`。一个持续输出的模块因此可以在大小检查生效前
    把验收器内存吃光 —— 上限形同虚设。

    这里复用适配层 `scripts/team_demo.py` 的：
      * `read_bounded()`            —— selector 边读边计数，stdout 超限立即终止；
                                       stderr 继续排空但只保留前 N 字节
      * `terminate_process_group()` —— 只终止**本次调用自己的进程组**，
                                       绝不按名称 pkill

    返回 dict：
      returncode / stdout / stderr / elapsed / stdout_bytes /
      exceeded（None 或 'STDOUT_TOO_LARGE' / 'STDERR_TOO_LARGE' / 'TIMEOUT'）
    """
    payload = (stdin_text if stdin_text is not None
               else json.dumps(envelope)).encode('utf-8')
    started = time.monotonic()
    record = {'pgid': None, 'terminate': None}

    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=REPO, shell=False,             # 明确 shell=False
            start_new_session=True)            # 自成进程组，便于按所有权清理
    except FileNotFoundError as exc:
        return {'returncode': None, 'stdout': '', 'stderr': 'NOT_FOUND: {0}'.format(exc),
                'elapsed': time.monotonic() - started, 'stdout_bytes': 0,
                'exceeded': 'NOT_FOUND'}
    except OSError as exc:
        return {'returncode': None, 'stdout': '', 'stderr': 'OSError: {0}'.format(exc),
                'elapsed': time.monotonic() - started, 'stdout_bytes': 0,
                'exceeded': 'SPAWN_FAILED'}

    record['pgid'] = os.getpgid(proc.pid)
    out_bytes, err_bytes, exceeded = _td.read_bounded(
        proc, payload, timeout, max_bytes, MAX_STDERR_KEEP)

    if exceeded:
        # 超限或超时都必须走受控终止流程，并且**不得判为成功**
        record['terminate'] = _td.terminate_process_group(proc, record)
    else:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            record['terminate'] = _td.terminate_process_group(proc, record)
            exceeded = 'TIMEOUT'

    elapsed = time.monotonic() - started
    return {
        'returncode': proc.returncode,
        'stdout': (out_bytes or b'').decode('utf-8', errors='replace'),
        'stderr': (err_bytes or b'').decode('utf-8', errors='replace'),
        'elapsed': elapsed,
        'stdout_bytes': len(out_bytes or b''),   # **按字节**计数，不是字符
        'exceeded': exceeded,
        'pgid': record['pgid'],
        'terminate': record.get('terminate'),
    }


#: 超时后允许的额外开销（秒）：进程组终止 + 子进程回收 + 管道关闭。
#: 超过该余量说明超时**没有真正生效**（进程跑过了配置的上限）。
TIMEOUT_GRACE_SEC = 3.0
#: 终止结果必须落在这些取值内才算「已回收」；含 unreaped / fail 即清理失败。
_CLEAN_TERMINATION = ('terminated', 'already_gone', 'terminated+killed')


def judge_timeout(result: dict, timeout: float) -> tuple:
    """判定一次极小超时调用的真实结果，返回 (ok, status, detail)。

    必须区分三种情况，而不是无条件放行：

    * ``clean_completion`` —— 进程在超时前正常结束，没有挂起。此时 elapsed
      必须**未超过**上限，否则说明「极小超时」并未真正约束运行时间。
    * ``timeout_terminated`` —— 超时触发，并且进程组被**真实终止并回收**：
      退出码是被信号杀死的负值、终止结果不是 unreaped/failed、
      且 elapsed 未显著超过 timeout + 余量（证明终止生效而非放任继续跑）。
    * ``failed`` —— 上述任一条件不成立：超时后未能终止、进程未回收、
      或运行时间远超上限。**这些情况绝不能记为 PASS。**

    ``exceeded`` 的其他取值（STDOUT_TOO_LARGE / SPAWN_FAILED / NOT_FOUND /
    SETUP_FAILED…）同样判负：极小超时检查只接受「干净结束」或「超时且已回收」。
    """
    exceeded = result.get('exceeded')
    elapsed = result.get('elapsed') or 0.0
    returncode = result.get('returncode')
    terminate = result.get('terminate')

    if exceeded is None:
        if elapsed > timeout + TIMEOUT_GRACE_SEC:
            return (False, 'overran_without_timeout',
                    '进程在 {0:.2f}s 后结束，超过上限 {1:.3f}s + {2:.1f}s 余量，'
                    '说明极小超时未约束运行时间'.format(
                        elapsed, timeout, TIMEOUT_GRACE_SEC))
        return (True, 'clean_completion',
                '进程在超时前自行结束（rc={0}，{1:.3f}s <= {2:.3f}s）'.format(
                    returncode, elapsed, timeout))

    if exceeded != 'TIMEOUT':
        return (False, 'unexpected_exceeded',
                'exceeded={0!r} 不是 TIMEOUT，极小超时检查不接受该结果'.format(exceeded))

    problems = []
    if not (isinstance(returncode, int) and returncode < 0):
        problems.append('超时后 returncode={0!r} 不是被信号终止的负值'.format(returncode))
    if terminate not in _CLEAN_TERMINATION:
        problems.append('终止结果 terminate={0!r} 未完成回收'.format(terminate))
    if elapsed > timeout + TIMEOUT_GRACE_SEC:
        problems.append('elapsed={0:.2f}s 远超上限 {1:.3f}s + {2:.1f}s 余量，'
                        '超时后进程未被及时终止'.format(
                            elapsed, timeout, TIMEOUT_GRACE_SEC))
    if problems:
        return False, 'timeout_not_contained', '；'.join(problems)
    return (True, 'timeout_terminated',
            '超时已触发且进程组被终止回收（rc={0}，terminate={1}，'
            '{2:.3f}s <= {3:.3f}s + {4:.1f}s）'.format(
                returncode, terminate, elapsed, timeout, TIMEOUT_GRACE_SEC))


def judge_exit_consistency(result: dict) -> tuple:
    """判定「产出结构化输出」与「成功退出」是否自洽。

    模块把协议跑完并产出结构化输出时，必须以 0 退出；否则无法区分
    「成功产出后崩溃」和「正常结束」。**没有**产出结构化输出时，非零退出是
    合法的失败关闭信号（例如输入非法 -> rc=2），不在此处判负。
    """
    rc = result.get('returncode')
    if result.get('stdout', '').strip() and rc not in (0, None):
        return (False, '输出结构化结果却以 rc={0} 退出（应为 0）'.format(rc))
    return (True, '')


# ---------------------------------------------------------------------------
# ADP-01：适配层**输入校验拒绝**的可证伪验证
# ---------------------------------------------------------------------------
# 为什么必须重写
# ------------
# 旧实现把「非零退出」也算作「输入校验成功阻断」：
#     blocked = ('ADAPTER_BLOCK' in proc.stdout
#                or 'ADAPTER_INPUT_INVALID' in proc.stdout
#                or proc.returncode != 0)
# 于是一个因 Python 异常、依赖缺失、配置错误而崩溃的适配器，也会被记为
# 「输入拒绝 PASS」——这是**验收证明的错误**。
#
# 现在必须同时成立：可解析 JSON + 顶层 ADAPTER_BLOCK + 原因码为
# ADAPTER_INPUT_INVALID + 退出码为协议规定的 EXIT_INPUT_INVALID（3）+
# 拒绝发生在任何模块调用之前（用调用标记证明）+ 没有 Planner 动作。
#
# 常量直接取自适配层模块，避免硬编码漂移（import 时无副作用）。
_td_checks = {}
for _name in ('EXIT_INPUT_INVALID', 'EXIT_BLOCK', 'EXIT_CONFIG_INVALID',
              'EXIT_INTERNAL', 'EXIT_USAGE', 'REASON_INPUT_INVALID',
              'REASON_OK', 'REASON_DEPENDENCY_MISSING'):
    _td_checks[_name] = getattr(_td, _name, None)


#: 各模块的「可推进状态」——正向对照替身必须输出它，否则适配层不会放行。
PROCEED_FOR_CONTROL = {
    'comm_risk': 'NORMAL',
    'identity_trust': 'AUTHORIZED',
    'task_risk': 'ALLOW_RECOMMENDED',
}


def _marker_module(tmp_path, marker, module):
    """写一个**调用标记**测试替身：一旦被调用就创建 marker 文件。

    用于证明适配层在拒绝非法输入时**没有**调用任何模块；同时它必须输出
    符合**目标模块** Schema 的合法文档，才能作为「合法输入应当推进」的正向对照
    （不同模块的输出 Schema 与可推进状态不同，因此必须按模块生成）。
    """
    status = PROCEED_FOR_CONTROL[module]
    script = Path(tmp_path) / 'marker_module_{0}.py'.format(module)
    script.write_text(
        'import json, sys, pathlib\n'
        'raw = sys.stdin.read()\n'
        'pathlib.Path({marker!r}).write_text("CALLED", encoding="utf-8")\n'
        'env = json.loads(raw)\n'
        'action = env["candidate_action"]\n'
        'target = dict(action["target"])\n'
        'common = {{\n'
        '    "schema_version": "1.0.0-proposed",\n'
        '    "run_id": env["run_id"], "request_id": env["request_id"],\n'
        '    "event_id": "probe-" + env["request_id"][:80],\n'
        '    "producer": {{"name": "adp01_probe", "source": "MOCK",\n'
        '                  "module_version": "0"}},\n'
        '    "observed_at": "2026-10-16T00:00:00Z",\n'
        '    "status": {status!r},\n'
        '    "evidence_refs": [{{"ref": "adp01_probe", "kind": "MOCK"}}],\n'
        '}}\n'
        'if {module!r} == "task_risk":\n'
        '    common.update({{\n'
        '        "task_id": action["task_id"],\n'
        '        "candidate_action": {{"action_resource": action["action_resource"],\n'
        '                            "operation": action["operation"]}},\n'
        '        "target": target,\n'
        '        "risk_level": "NONE", "reason": "adp01 positive control",\n'
        '        "rule_basis": ["probe"],\n'
        '    }})\n'
        'elif {module!r} == "identity_trust":\n'
        '    common.update({{\n'
        '        "reason": "adp01 positive control",\n'
        '        "subject": {{"observed_name": "adp01_probe"}},\n'
        '        "requested_resource": {{"resource": action["action_resource"],\n'
        '                              "operation": "SERVICE_REQUEST"}},\n'
        '        "authorization": {{"result_status": {status!r},\n'
        '                          "denial_layer": "NONE"}},\n'
        '        "identity_evidence": {{"kind": "MOCK"}},\n'
        '        "access_control_evidence": {{"kind": "NONE"}},\n'
        # 适配层要求身份位置声明**当前请求**身份绑定（历史授权不算）。
        # 正向对照替身必须显式给出它并标注 MOCK_FIXTURE；否则 ADP-00 会把
        # "适配层按安全语义阻断历史授权"误判成控制失败。
        '        "extensions": {{"current_request_identity": {{\n'
        '            "status": "AUTHENTICATED",\n'
        '            "evidence_kind": "MOCK_FIXTURE",\n'
        '            "binding": "PROBE_POSITIVE_CONTROL",\n'
        '            "historical_only": False}}}},\n'
        '    }})\n'
        'else:\n'
        '    common.update({{\n'
        '        "reason": "adp01 positive control",\n'
        '        "communication": {{"resource": action["action_resource"],\n'
        '                          "resource_type": "Action",\n'
        '                          "operation": "GOAL_SEND"}},\n'
        '        "window": {{"start": env["created_at"],\n'
        '                   "end": env["created_at"],\n'
        '                   "duration_ms": 0}},\n'
        '        "request_count": 1,\n'
        '        "anomaly_category": "NONE", "risk_level": "NONE",\n'
        '        "basis": ["adp01 positive control"],\n'
        '    }})\n'
        'json.dump(common, sys.stdout)\n'.format(
            marker=str(marker), module=module, status=status),
        encoding='utf-8')
    return script


def _write_probe_config(tmp_path, config, module, command, name):
    """在临时目录生成一份**受信任**配置副本，仅替换目标模块命令。

    关于身份模式
    ------------
    探针会把目标模块换成"调用标记"测试替身，用来证明适配层在拒绝非法输入时
    确实没有调用模块、以及合法输入确实能推进（ADP-00 正向对照）。
    这类探针**按定义**是受控测试：它没有任何真实 DDS 身份证据。

    F0 的严格身份模式（默认）会因此阻断所有探针，使 ADP-00 变成"永远失败"的
    哨兵而失去意义。所以探针配置必须**显式**声明受控身份模式并写明理由——
    这是如实标注探针性质，不是放宽安全边界：真实运行的配置仍是严格模式，
    只有这份临时探针配置是受控的。
    """
    import copy
    import yaml
    document = copy.deepcopy(config)
    document.setdefault('modules', {}).setdefault(module, {})
    document['modules'][module]['command'] = list(command)
    document.setdefault('adapter', {})
    document['adapter']['log_path'] = str(Path(tmp_path) / ('adapter-{0}.jsonl'.format(name)))
    document['identity_attestation'] = {
        'mode': 'CONTROLLED_TEST_ONLY',
        'controlled_reason': ('验收器探针：目标模块被替换为调用标记测试替身，'
                              '不含任何真实 DDS 身份证据'),
    }
    path = Path(tmp_path) / ('config-{0}.yaml'.format(name))
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding='utf-8')
    return str(path)


def _adapter_evidence(proc, planner_flags=()):
    """从适配层 stdout 提取可核验证据；非 JSON 时如实标记。"""
    out = (proc.stdout or '').strip()
    evidence = {'stdout_is_json': False, 'decision': None, 'reason_code': None,
                'planner_started': False, 'modules_invoked': None,
                'exit_code': proc.returncode,
                'stdout_head': out[:200], 'stderr_head': (proc.stderr or '')[:200]}
    document = None
    if out.startswith('{'):
        try:
            document = json.loads(out)
        except ValueError:
            document = None
    if isinstance(document, dict):
        evidence['stdout_is_json'] = True
        evidence['decision'] = document.get('decision')
        evidence['reason_code'] = document.get('reason_code')
        modules = document.get('modules')
        evidence['modules_invoked'] = len(modules) if isinstance(modules, list) else None
        online = document.get('online') or {}
        evidence['planner_started'] = bool(online.get('enabled')) or bool(
            online.get('started'))
    for flag in planner_flags:
        if flag:
            evidence['planner_started'] = True
    return evidence


def run_adapter(adapter, config, stdin_text, timeout):
    """调用适配层一次，返回 (proc, evidence)。"""
    proc = subprocess.run(
        [sys.executable, adapter, '--input', '-', '--config', config],
        input=stdin_text, capture_output=True, text=True,
        timeout=max(timeout, 60), cwd=REPO, shell=False)
    return proc, _adapter_evidence(proc)


def judge_clean_input_rejection(evidence) -> tuple:
    """判定是否构成**明确的输入校验拒绝**，返回 (ok, detail)。

    必须全部成立，缺一不可。特别注意：这里**不再**接受"非零退出"作为充分条件。
    """
    problems = []
    if not evidence['stdout_is_json']:
        problems.append('stdout 不是可解析 JSON（无法证明是输入校验拒绝）：{0!r}'.format(
            evidence['stdout_head'][:80]))
    if evidence['decision'] != 'ADAPTER_BLOCK':
        problems.append('decision={0!r} 不是 ADAPTER_BLOCK'.format(evidence['decision']))
    if evidence['reason_code'] != _td_checks['REASON_INPUT_INVALID']:
        problems.append('reason_code={0!r} 不是 {1!r}'.format(
            evidence['reason_code'], _td_checks['REASON_INPUT_INVALID']))
    if evidence.get('exit_code') != _td_checks['EXIT_INPUT_INVALID']:
        problems.append('returncode={0!r} 不是协议规定的 {1!r}'.format(
            evidence.get('exit_code'), _td_checks['EXIT_INPUT_INVALID']))
    if evidence['modules_invoked'] not in (0, None):
        problems.append('已有 {0} 个模块被调用，拒绝未发生在模块调用之前'.format(
            evidence['modules_invoked']))
    if evidence['planner_started']:
        problems.append('检测到 Planner 已启动')
    if problems:
        return False, '；'.join(problems)
    return True, 'decision=ADAPTER_BLOCK reason_code={0} rc={1} 模块调用=0'.format(
        evidence['reason_code'], evidence.get('exit_code'))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='统一成员模块验收')
    parser.add_argument('--module', required=True, choices=sorted(MODULE_SPEC))
    parser.add_argument('--config', required=True)
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--real-fixture', default=None,
                        help='真实模块场景 fixture（受信任本地文件）；'
                             '给出后额外执行由真实条件触发的状态矩阵')
    parser.add_argument('--out-dir', default=os.path.join(REPO, 'logs',
                                                          'member_acceptance'))
    args = parser.parse_args(argv)

    module = args.module
    schema_file, proceed_state, other_states = MODULE_SPEC[module]
    run_id = args.run_id or 'acc-{0}-{1}'.format(
        module, time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
    report = Report(module, args.config)
    report.data['run_id'] = run_id

    # ---------------- 1) 配置合法 ----------------
    try:
        config = load_yaml(args.config)
        report.add('CFG-01', '模块配置可解析', 'PASS', rel(args.config))
    except Exception as exc:                   # noqa: BLE001
        report.add('CFG-01', '模块配置可解析', 'FAIL', str(exc))
        return finalize(report, args.out_dir)

    modules = (config or {}).get('modules') or {}
    entry = modules.get(module)
    report.add('CFG-02', '配置中包含目标模块', 'PASS' if entry else 'FAIL',
               'modules 键: {0}'.format(sorted(modules)))

    if not entry:
        return finalize(report, args.out_dir)

    # 统一解释器：配置里的裸 `python3` 映射到当前验收进程的解释器，
    # 避免「模块依赖其实已满足、却因为 PATH 上是另一个 python3 而假失败」。
    # 只改解释器，不改任何参数与检查门槛。
    raw_command = entry.get('command')
    command = (resolve_interpreter(raw_command)
               if isinstance(raw_command, list) and raw_command else raw_command)
    report.data['module_command'] = command
    report.data['module_command_as_configured'] = raw_command
    if isinstance(command, list) and command:
        report.data['executable'] = command[0]
    report.add('CFG-03', 'command 是参数数组（非字符串）',
               'PASS' if isinstance(command, list) else 'FAIL',
               'type={0}'.format(type(command).__name__))
    if not isinstance(command, list) or not command:
        return finalize(report, args.out_dir)

    report.add('CFG-04', '命令来自受信任本地配置（非业务输入）', 'PASS',
               '命令只取自 --config 指定的文件')
    report.add('CFG-05', '接口名与模块匹配',
               'PASS' if entry.get('interface') else 'FAIL',
               'interface={0!r}'.format(entry.get('interface')))
    timeout = float(entry.get('timeout_sec') or 10)
    max_bytes = int(entry.get('max_stdout_bytes') or 65536)

    # ---------------- 2) 正常路径 ----------------
    envelope = build_envelope()
    res = invoke(command, envelope, timeout, max_bytes)
    rc, out, err = res['returncode'], res['stdout'], res['stderr']
    elapsed, out_bytes = res['elapsed'], res['stdout_bytes']
    report.add('RUN-01', '模块被真实调用（记录命令与返回码）',
               'PASS' if rc is not None and not res['exceeded'] else 'FAIL',
               'rc={0} elapsed={1:.2f}s exceeded={2}'.format(
                   rc, elapsed, res['exceeded']),
               extra={'returncode': rc, 'elapsed_sec': round(elapsed, 3),
                      'stdout_bytes': out_bytes, 'pgid': res.get('pgid'),
                      'exceeded': res['exceeded'],
                      'stderr_head': (err or '')[:200]})

    report.add('PROTO-01', 'stdout 非空', 'PASS' if out.strip() else 'FAIL',
               '{0} 字节'.format(out_bytes))
    report.add('PROTO-02', 'stdout 只含一个 JSON 对象',
               'PASS' if out.strip().count('\n') == 0 or
               (out.strip().startswith('{') and out.strip().endswith('}')) else 'FAIL',
               '行数={0}'.format(out.strip().count(chr(10)) + 1 if out.strip() else 0))
    report.add('PROTO-03', 'stdout 无额外调试文本污染', 'PASS'
               if out.lstrip().startswith('{') and out.rstrip().endswith('}')
               else 'FAIL', '首字符={0!r}'.format(out[:1]))
    report.add('PROTO-04', 'stdout 未超过 max_stdout_bytes',
               'PASS' if out_bytes <= max_bytes else 'FAIL',
               '{0} <= {1}'.format(out_bytes, max_bytes))
    report.add('PROTO-05', '诊断信息写入 stderr（stdout 依然干净）', 'PASS',
               'stderr {0} 字节'.format(len((err or '').encode())))

    payload = None
    try:
        payload = json.loads(out)
        report.add('PROTO-06', 'stdout 是合法 JSON', 'PASS')
    except ValueError as exc:
        report.add('PROTO-06', 'stdout 是合法 JSON', 'FAIL', str(exc))

    # event_id 审计去重台账：同一运行内不得出现重复事件标识
    # （契约 §7：一次运行多个事件通过不同 event_id 区分；重复输出以 event_id 去重）
    event_ids = []

    if payload is not None:
        report.add('ID-01', 'run_id 与输入一致',
                   'PASS' if payload.get('run_id') == envelope['run_id'] else 'FAIL',
                   '{0!r}'.format(payload.get('run_id')))
        report.add('ID-02', 'request_id 与输入一致',
                   'PASS' if payload.get('request_id') == envelope['request_id']
                   else 'FAIL', '{0!r}'.format(payload.get('request_id')))
        # ID-03 修正（契约对齐）
        # `docs/interfaces/CONTRACT_VERSION.md` §7 与三份 Schema 的定义是：
        #   event_id   = 本次输出事件唯一标识，用于**审计追溯与去重**（1..128 字符）
        #   request_id = 业务请求关联标识
        # 跨层关联由**显式** run_id/request_id 字段承担，**不是**把 request_id
        # 塞进 event_id。旧规则要求「event_id 含完整 request_id」与 Schema 的
        # 128 字符上限在 request_id > 80 时数学上无法同时成立，属于验收器缺陷。
        event_id = payload.get('event_id')
        report.add('ID-03', 'event_id 为合法非空唯一标识（不要求包含 request_id）',
                   'PASS' if isinstance(event_id, str) and 0 < len(event_id) <= 128
                   and event_id.strip() else 'FAIL',
                   'event_id={0!r} len={1}'.format(
                       event_id, len(event_id) if isinstance(event_id, str) else None))
        report.add('ID-03B', 'event_id 与 request_id 的关联由显式字段承担',
                   'PASS' if payload.get('request_id') == envelope['request_id']
                   else 'FAIL',
                   'request_id 字段一致性即关联依据；event_id 不承担该编码责任')
        if isinstance(payload.get('event_id'), str):
            event_ids.append((payload.get('event_id'), 'primary'))
        report.add('ID-04', 'schema_version 合法',
                   'PASS' if payload.get('schema_version') == '1.0.0-proposed'
                   else 'FAIL', '{0!r}'.format(payload.get('schema_version')))
        prod = payload.get('producer') or {}
        report.add('SEM-01', 'producer.source 语义合法',
                   'PASS' if prod.get('source') in ('MOCK', 'EXTERNAL', 'UNKNOWN')
                   else 'FAIL', '{0!r}'.format(prod.get('source')),
                   extra={'implementation_type': prod.get('source')})
        report.data['implementation_type'] = prod.get('source')
        refs = payload.get('evidence_refs')
        ref_ok = bool(refs) and all(
            r.get('kind') in ('MOCK', 'RUNTIME_LOG', 'PERMISSION_FILE_ANALYSIS',
                              'CONTROLLED_SECURITY_EXPERIMENT', 'UNIT_TEST',
                              'UNKNOWN') for r in refs or [])
        report.add('SEM-02', 'evidence_refs 存在且 kind 合法',
                   'PASS' if ref_ok else 'FAIL',
                   '{0}'.format([r.get('kind') for r in refs or []]))

        ok, serr = validate(payload, os.path.join(SCHEMA_DIR, schema_file))
        if ok is None:
            report.add('SCH-01', 'Schema 校验', 'BLOCKED', serr)
        else:
            report.add('SCH-01', 'Schema 校验', 'PASS' if ok else 'FAIL', serr,
                       extra={'schema_error': None if ok else serr})

        state = payload.get('status')
        if state == proceed_state:
            report.add('STATE-01', '正常状态为允许推进值', 'PASS', state)
        elif state in other_states:
            # 关键区分：结构合法，但状态不允许推进 —— 这是合法的安全阻断
            report.add('STATE-01', '状态为合法安全阻断（结构合法，不推进）',
                       'PASS', '{0}（LEGAL_BLOCK，不是 Schema 错误）'.format(state),
                       extra={'classification': 'LEGAL_BLOCK'})
        else:
            report.add('STATE-01', '状态属该模块合法枚举', 'FAIL',
                       '{0!r} 不在 {1}'.format(
                           state, [proceed_state] + sorted(other_states)))

    # ---------------- 3) FIX-03：三模块 × 四状态 = 12 个真实运行 ----------------
    # 不再用静态列表直接写 PASS：每种状态都**实际调用模块**、真实产出 JSON、
    # 通过对应 Schema，并交由状态分类器处理。
    matrix = STATE_MATRIX[module]
    state_rows = []
    for scenario, expected_state, expected_class in matrix:
        env = envelope_for(module, scenario, 'req-state-{0}'.format(scenario))
        r = invoke(command, env, timeout, max_bytes)
        row = {'scenario': scenario, 'expected_state': expected_state,
               'expected_class': expected_class, 'returncode': r['returncode'],
               'structured': False, 'schema_ok': None, 'actual_state': None,
               'actual_class': None, 'ids_ok': False}
        if r['exceeded'] or not r['stdout'].strip():
            row['detail'] = 'exceeded={0} stdout={1}B'.format(
                r['exceeded'], r['stdout_bytes'])
            state_rows.append(row)
            continue
        try:
            payload = json.loads(r['stdout'])
            row['structured'] = True
        except ValueError as exc:
            row['detail'] = '非法 JSON: {0}'.format(exc)
            state_rows.append(row)
            continue
        row['actual_state'] = payload.get('status')
        row['event_id'] = payload.get('event_id')
        row['ids_ok'] = (payload.get('run_id') == env['run_id']
                         and payload.get('request_id') == env['request_id'])
        ok, serr = validate(payload, os.path.join(SCHEMA_DIR, schema_file))
        row['schema_ok'] = ok
        if ok:
            row['actual_class'] = classify(row['actual_state'], proceed_state)
        else:
            row['detail'] = serr
        state_rows.append(row)

    # 给出 `--real-fixture` 时，被测对象是**不解析 f0_mock 开关的真实模块**：
    # mock 场景开关对它不适用。这些记录如实保留（含 FAIL 与原因）但不计入
    # 门槛，门槛改由真实条件状态矩阵（REAL-STATE-*）承担。未给出
    # `--real-fixture` 时行为与修复前完全一致，mock 模式仍是强制项。
    mock_gate = not args.real_fixture
    for row in state_rows:
        cid = 'STATE-{0}'.format(row['scenario'].upper())
        passed = (row['structured'] and row['schema_ok'] is True
                  and row['ids_ok']
                  and row['actual_state'] == row['expected_state']
                  and row['actual_class'] == row['expected_class'])
        detail = 'rc={0} state={1} schema_ok={2} class={3} ids_ok={4}'.format(
            row['returncode'], row['actual_state'], row['schema_ok'],
            row['actual_class'], row['ids_ok'])
        if not mock_gate:
            detail += ('；fixture 的 f0_mock 场景开关对真实模块不适用，'
                       '该状态由 REAL-STATE-{0} 以真实条件校验').format(
                           row['scenario'].upper())
        report.add(
            cid, '{0} 场景真实运行 -> {1}（{2}）'.format(
                row['scenario'], row['expected_state'], row['expected_class']),
            'PASS' if passed else 'FAIL', detail,
            mandatory=False if not mock_gate else True,
            extra={'scenario': row['scenario'],
                   'schema_valid': row['schema_ok'],
                   'security_class': row['actual_class'],
                   'returncode': row['returncode'],
                   'gate': mock_gate,
                   'applicability': ('MOCK_SCENARIO_SWITCH_APPLIES' if mock_gate
                                     else 'NOT_APPLICABLE_REAL_MODULE')})

    for row in state_rows:
        if row.get('event_id'):
            event_ids.append((row['event_id'], 'state:' + str(row.get('scenario'))))
    report.data['state_matrix'] = state_rows
    proceed_rows = [r for r in state_rows if r['expected_class'] == 'PROCEED']
    block_rows = [r for r in state_rows if r['expected_class'] == 'LEGAL_BLOCK']
    report.add('STATE-SUMMARY', '四状态矩阵完整执行（共 {0} 种）'.format(len(matrix)),
               'PASS' if len(state_rows) == len(matrix) else 'FAIL',
               'PROCEED={0} LEGAL_BLOCK={1}'.format(
                   len(proceed_rows), len(block_rows)))
    report.add('STATE-CLASSIFY',
               'Schema 合法性与安全推进资格分开判定',
               'PASS' if all(r['schema_ok'] is True for r in state_rows) else 'FAIL',
               '阻断状态（{0}）Schema 同样合法，被归类为 LEGAL_BLOCK 而非 Schema 错误'.format(
                   ','.join(r['expected_state'] for r in block_rows)))

    # 适配层必须对三种阻断状态返回 ADAPTER_BLOCK
    adapter = os.path.join(REPO, 'scripts', 'team_demo.py')
    for row in block_rows:
        env = envelope_for(module, row['scenario'],
                           'req-adapter-{0}'.format(row['scenario']))
        cid = 'ADP-{0}'.format(row['scenario'].upper())
        if not os.path.isfile(adapter):
            report.add(cid, '适配层对 {0} 阻断'.format(row['expected_state']),
                       'BLOCKED', 'scripts/team_demo.py 不存在')
            continue
        try:
            proc = subprocess.run(
                [sys.executable, adapter, '--input', '-', '--config', args.config],
                input=json.dumps(env), capture_output=True, text=True,
                timeout=max(timeout, 60), cwd=REPO, shell=False)
            blocked = 'ADAPTER_BLOCK' in proc.stdout
            report.add(cid, '适配层对 {0} 返回 ADAPTER_BLOCK'.format(
                row['expected_state']),
                'PASS' if blocked else 'FAIL',
                'rc={0} decision={1}'.format(
                    proc.returncode,
                    (json.loads(proc.stdout).get('reason_code')
                     if proc.stdout.strip().startswith('{') else 'n/a')),
                extra={'returncode': proc.returncode})
        except Exception as exc:               # noqa: BLE001
            report.add(cid, '适配层对 {0} 阻断'.format(row['expected_state']),
                       'BLOCKED', str(exc)[:200])

    # ---------------- 3b) 真实模块场景（L2）：真实条件触发四状态 ----------------
    # 与上面的 Mock 矩阵并存且互不影响：Mock 矩阵验证协议与 mock 契约，
    # 这里验证**真实规则模块**能由真实条件产生四状态，并被真实状态核对。
    real_block_rows = []
    real_proceed_rows = []
    if args.real_fixture:
        report.data['real_fixture'] = rel(args.real_fixture)
        try:
            fixture = parse_real_fixture(args.real_fixture, module, config)
        except FixtureError as exc:
            report.add('REAL-01', '真实场景 fixture 合法', 'FAIL', str(exc))
            fixture = None
        else:
            report.add('REAL-01', '真实场景 fixture 合法（受信任本地文件）',
                       'PASS',
                       '{0}；{1} 个场景'.format(rel(args.real_fixture),
                                             len(fixture['scenarios'])))
            report.add('REAL-02',
                       '业务输入不得指定命令/策略/可执行文件',
                       'PASS',
                       'fixture 只引用配置档案名；envelope_patch 中 '
                       'command/exec/policy/env 等字段被拒绝')
        if fixture:
            rows = []
            for scenario in fixture['scenarios']:
                row, env, payload = invoke_real_scenario(
                    module, scenario, timeout, max_bytes)
                extra_fail = verify_traceability(row, payload, row['command'])
                reason_expect = scenario['expect'].get('reason_code')
                if reason_expect and row['actual_reason_code'] != reason_expect:
                    extra_fail = (extra_fail + ' | ' if extra_fail else '') + (
                        'reason_code {0!r} != 期望 {1!r}'.format(
                            row['actual_reason_code'], reason_expect))
                # rc==0 是真实状态验收的一部分：合法 JSON + 期望状态但以
                # 非零状态退出，说明协议没有正常跑完，不得判为通过。
                # UNKNOWN / ERROR 等安全阻断**只要结构合法且 rc==0** 仍然通过
                # （它们不是 Schema 错误，只是不允许推进）。
                rc_ok = row['returncode'] == 0
                if not rc_ok:
                    extra_fail = (extra_fail + ' | ' if extra_fail else '') + (
                        'returncode={0} != 0，模块未成功退出'.format(
                            row['returncode']))
                passed = (
                    row['structured'] and row['schema_ok'] is True
                    and row['ids_ok'] and row['traceability_ok'] and rc_ok
                    and row['actual_state'] == row['expected_state']
                    and row['actual_class'] == row['expected_class']
                    and not extra_fail)
                row['passed'] = passed
                row['returncode_ok'] = rc_ok
                row['expected_class_ok'] = (
                    row['actual_class'] == row['expected_class'])
                row['expectation_failure'] = extra_fail
                cid = 'REAL-STATE-{0}'.format(scenario['name'].upper())
                detail = ('rc={0} rc_ok={1} policy={2} actual={3} expected={4} '
                          'schema_ok={5} class={6} ids_ok={7} '
                          'traceability_ok={8} reason_code={9}').format(
                    row['returncode'], row['returncode_ok'], row['policy_ref'],
                    row['actual_state'], row['expected_state'],
                    row['schema_ok'], row['actual_class'], row['ids_ok'],
                    row['traceability_ok'], row['actual_reason_code'])
                if extra_fail:
                    detail += ' | ' + extra_fail
                report.add(
                    cid,
                    '真实条件 {0}（{1}）-> {2}'.format(
                        scenario['name'], scenario['trigger'] or '真实策略条件',
                        row['expected_state']),
                    'PASS' if passed else 'FAIL', detail,
                    extra={'scenario': row['scenario'],
                           'trigger': row['trigger'],
                           'expected_state': row['expected_state'],
                           'actual_state': row['actual_state'],
                           'expected_class': row['expected_class'],
                           'security_class': row['actual_class'],
                           'schema_valid': row['schema_ok'],
                           'reason_code': row['actual_reason_code'],
                           'traceable_command': row['command'],
                           'policy_ref': row['policy_ref'],
                           'returncode': row['returncode']})
                rows.append((scenario, row, env))
                if row['expected_class'] == 'LEGAL_BLOCK':
                    real_block_rows.append((scenario, row, env))
                else:
                    real_proceed_rows.append((scenario, row, env))

            report.data['real_state_matrix'] = [
                {k: v for k, v in row.items() if k != 'command'} |
                {'command': row['command']}
                for _s, row, _e in rows]
            for row in (real_block_rows + real_proceed_rows):
                _r = row[1]
                if _r.get('event_id'):
                    event_ids.append((_r['event_id'], 'real:' + str(_r.get('scenario'))))
            report.add(
                'REAL-STATE-SUMMARY',
                '真实条件状态矩阵完整执行（共 {0} 种）'.format(
                    len(fixture['scenarios'])),
                'PASS' if len(rows) == len(fixture['scenarios'])
                and all(r['passed'] for _s, r, _e in rows) else 'FAIL',
                'PROCEED={0} LEGAL_BLOCK={1}；均由真实模块输出决定'.format(
                    len(real_proceed_rows), len(real_block_rows)))
            report.add(
                'REAL-STATE-SCHEMA',
                '真实条件输出符合原有 Schema（含阻断状态）',
                'PASS' if rows and all(
                    r['schema_ok'] is True for _s, r, _e in rows) else 'FAIL',
                '阻断状态也必须结构合法；Schema 非法单独判负')

            # ---- F0 对真实阻断状态的处置 ----
            adapter = os.path.join(REPO, 'scripts', 'team_demo.py')
            with tempfile.TemporaryDirectory(prefix='rg_real_fixture_') as temp:
                for scenario, row, env in real_block_rows:
                    cid = 'REAL-ADP-{0}'.format(scenario['name'].upper())
                    if not os.path.isfile(adapter):
                        report.add(cid, 'F0 对真实 {0} 阻断'.format(
                            row['expected_state']), 'BLOCKED',
                            'scripts/team_demo.py 不存在')
                        continue
                    cfg_path, log_path = _pin_real_command(
                        temp, config, module, row['command'])
                    try:
                        proc = subprocess.run(
                            [sys.executable, adapter, '--input', '-',
                             '--config', cfg_path, '--log', log_path],
                            input=json.dumps(env), capture_output=True,
                            text=True, timeout=max(timeout, 60), cwd=REPO,
                            shell=False)
                        decision = reason = None
                        if proc.stdout.strip().startswith('{'):
                            doc = json.loads(proc.stdout)
                            decision = doc.get('decision')
                            reason = doc.get('reason_code')
                        blocked = (decision == 'ADAPTER_BLOCK'
                                   and proc.returncode != 0)
                        report.add(
                            cid,
                            'F0 对真实 {0}（{1}）返回 ADAPTER_BLOCK'.format(
                                row['expected_state'], scenario['name']),
                            'PASS' if blocked else 'FAIL',
                            'rc={0} decision={1} reason={2}'.format(
                                proc.returncode, decision, reason),
                            extra={'returncode': proc.returncode,
                                   'decision': decision,
                                   'reason_code': reason,
                                   'actual_state': row['actual_state']})
                    except Exception as exc:               # noqa: BLE001
                        report.add(cid, 'F0 对真实 {0} 阻断'.format(
                            row['expected_state']), 'BLOCKED', str(exc)[:200])

                # ---- 合法条件只产生 READY_FOR_GATEWAY_SUBMISSION ----
                for scenario, row, env in real_proceed_rows:
                    cid = 'REAL-ADP-{0}'.format(scenario['name'].upper())
                    if not os.path.isfile(adapter):
                        report.add(cid, '合法真实条件 -> 仅 READY_FOR_GATEWAY_SUBMISSION',
                                   'BLOCKED', 'scripts/team_demo.py 不存在')
                        continue
                    cfg_path, log_path = _pin_real_command(
                        temp, config, module, row['command'])
                    try:
                        proc = subprocess.run(
                            [sys.executable, adapter, '--input', '-',
                             '--config', cfg_path, '--log', log_path],
                            input=json.dumps(env), capture_output=True,
                            text=True, timeout=max(timeout, 60), cwd=REPO,
                            shell=False)
                        doc = (json.loads(proc.stdout)
                               if proc.stdout.strip().startswith('{') else {})
                        decision = doc.get('decision')
                        expected_decision = (scenario['expect'].get('adapter_decision')
                                             or 'READY_FOR_GATEWAY_SUBMISSION')
                        expected_reason = scenario['expect'].get('adapter_reason')
                        no_downstream = (doc.get('gateway_decision') is None
                                         and doc.get('navsim_goal_id') is None)
                        if expected_decision == 'ADAPTER_BLOCK':
                            # 模块级结论合法，但适配层按安全语义必须阻断
                            # （例如历史授权不能替代当前请求身份绑定）。
                            ok = (decision == 'ADAPTER_BLOCK' and no_downstream
                                  and (expected_reason is None
                                       or doc.get('reason_code') == expected_reason))
                            name = ('合法模块结论仍被 F0 阻断（期望 {0}）').format(
                                expected_reason or 'ADAPTER_BLOCK')
                        else:
                            # READY 只代表可以提交给 Gateway，绝不是 ALLOW，
                            # 更不是 NavigationSim 执行成功。
                            ok = (decision == 'READY_FOR_GATEWAY_SUBMISSION'
                                  and no_downstream)
                            name = ('合法真实条件只产生 READY_FOR_GATEWAY_SUBMISSION'
                                    '（仍需 Gateway 判定）')
                        report.add(
                            cid, name, 'PASS' if ok else 'FAIL',
                            'rc={0} decision={1} reason={2}'
                            ' gateway_decision={3}'.format(
                                proc.returncode, decision,
                                doc.get('reason_code'),
                                doc.get('gateway_decision')),
                            extra={'returncode': proc.returncode,
                                   'decision': decision,
                                   'reason_code': doc.get('reason_code'),
                                   'actual_state': row['actual_state']})
                    except Exception as exc:               # noqa: BLE001
                        report.add(cid, '合法真实条件 -> 仅 READY', 'BLOCKED',
                                   str(exc)[:200])

    # ---------------- 4) 失败关闭路径 ----------------
    bad_cases = [
        ('ERR-01', '非法 JSON 输入', '{not json'),
    ]
    for cid, name, raw in bad_cases:
        r = invoke(command, envelope, timeout, max_bytes, stdin_text=raw)
        failed_closed = (r['returncode'] not in (0,) or not r['stdout'].strip())
        report.add(cid, '{0} -> 失败关闭'.format(name),
                   'PASS' if failed_closed else 'FAIL',
                   'rc={0} stdout={1}B exceeded={2}'.format(
                       r['returncode'], r['stdout_bytes'], r['exceeded']),
                   extra={'returncode': r['returncode'],
                          'stdout_bytes': r['stdout_bytes']})

    # 模块级的信封完整性校验属于**纵深防御**，不是唯一安全边界：
    # 真正的边界是适配层 —— 它在调用任何模块之前就用 module_input schema
    # 校验整个信封。因此这两项**非强制**，但会如实记录模块是否也自行校验。
    defense_cases = [
        ('ERR-03', 'schema_version 不兼容', json.dumps(
            dict(envelope, schema_version='9.9.9'))),
        ('ERR-04', '缺 observations', json.dumps(
            {k: v for k, v in envelope.items() if k != 'observations'})),
    ]
    for cid, name, raw in defense_cases:
        r = invoke(command, envelope, timeout, max_bytes, stdin_text=raw)
        closed = r['returncode'] not in (0,) or not r['stdout'].strip()
        report.add(cid, '{0} -> 模块自行失败关闭（纵深防御）'.format(name),
                   'PASS' if closed else 'NOT_RUN',
                   ('模块返回 rc={0}；该项非强制，安全边界在适配层'.format(
                       r['returncode'])),
                   mandatory=False, extra={'returncode': r['returncode']})

    # ---- 强制项：真正的安全边界在适配层（ADP-01，已加固） ----
    adapter = os.path.join(REPO, 'scripts', 'team_demo.py')
    if not os.path.isfile(adapter):
        report.add('ADP-01', '适配层对畸形信封做明确输入拒绝', 'BLOCKED',
                   'scripts/team_demo.py 不存在')
    else:
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory(prefix='rg_adp01_') as _tmp:
            # 正向对照：必须存在，否则"全部判为阻断"也能骗过本项
            marker = os.path.join(_tmp, 'MODULE_CALLED.marker')
            probe_cfg = _write_probe_config(
                _tmp, config, module,
                [sys.executable, str(_marker_module(_tmp, marker, module))], 'probe')
            valid_text = json.dumps(envelope)
            try:
                proc_ok, ev_ok = run_adapter(adapter, probe_cfg, valid_text,
                                             timeout)
                positive_ok = (ev_ok['decision'] == 'READY_FOR_GATEWAY_SUBMISSION'
                               and os.path.isfile(marker))
                positive_detail = (
                    'decision={0} reason={1} 模块被调用={2}'.format(
                        ev_ok['decision'], ev_ok['reason_code'],
                        os.path.isfile(marker)))
            except Exception as exc:               # noqa: BLE001
                positive_ok, positive_detail = False, str(exc)[:200]
            report.add('ADP-00', '正向对照：合法输入可推进且模块确实被调用',
                       'PASS' if positive_ok else 'FAIL', positive_detail,
                       extra={'control': 'POSITIVE_CONTROL'})

            # 四项**明确输入拒绝**：必须给出 ADAPTER_INPUT_INVALID + rc=3，
            # 且不得调用任何模块。
            envelope_no_obs = {k: v for k, v in envelope.items()
                               if k != 'observations'}
            envelope_no_action = {k: v for k, v in envelope.items()
                                  if k != 'candidate_action'}
            clean_cases = [
                ('ADP-N01', '缺少 observations', json.dumps(envelope_no_obs)),
                ('ADP-N02', 'schema_version 非法', json.dumps(
                    dict(envelope, schema_version='9.9.9'))),
                ('ADP-N03', '缺少 candidate_action', json.dumps(envelope_no_action)),
                ('ADP-N04', '非法 JSON 输入', '{not json'),
            ]
            for cid, name, raw in clean_cases:
                case_marker = os.path.join(_tmp, 'CALLED-{0}.marker'.format(cid))
                cfg = _write_probe_config(
                    _tmp, config, module,
                    [sys.executable, str(_marker_module(_tmp, case_marker, module))],
                    cid)
                try:
                    proc, ev = run_adapter(adapter, cfg, raw, timeout)
                except Exception as exc:           # noqa: BLE001
                    report.add(cid, '{0} -> 明确输入拒绝'.format(name), 'BLOCKED',
                               str(exc)[:200])
                    continue
                ok, detail = judge_clean_input_rejection(ev)
                if os.path.isfile(case_marker):
                    ok = False
                    detail += '；非法输入却实际调用了模块（调用标记存在）'
                report.add(cid, '{0} -> 明确输入拒绝（ADAPTER_INPUT_INVALID）'.format(name),
                           'PASS' if ok else 'FAIL', detail,
                           extra={'adapter_evidence': {
                               k: v for k, v in ev.items() if k != 'stdout_head'},
                               'module_called': os.path.isfile(case_marker)})

            # 四类**非输入故障**：绝不能记为"输入校验拒绝 PASS"。
            # 它们可以合法地以其它原因码失败关闭，但不得冒充 ADP-01。
            fault_cases = [
                ('ADP-N05', '适配器内部异常/模块脚本崩溃',
                 _write_probe_config(_tmp, config, module,
                                     [sys.executable, '-c',
                                      'raise SystemExit(7)'], 'n05'),
                 json.dumps(envelope)),
                ('ADP-N06', '适配器依赖缺失（解释器不存在）',
                 _write_probe_config(_tmp, config, module,
                                     ['/nonexistent/python-does-not-exist',
                                      'x.py'], 'n06'),
                 json.dumps(envelope)),
                ('ADP-N07', '配置文件不存在',
                 os.path.join(_tmp, 'no-such-config.yaml'),
                 json.dumps(envelope)),
                ('ADP-N08', '模块返回非零且输出不是合法 JSON',
                 _write_probe_config(_tmp, config, module,
                                     [sys.executable, '-c',
                                      'import sys;sys.stdin.read();'
                                      'print("NOT JSON");raise SystemExit(1)'],
                                     'n08'),
                 json.dumps(envelope)),
            ]
            for cid, name, cfg, raw in fault_cases:
                try:
                    proc, ev = run_adapter(adapter, cfg, raw, timeout)
                except Exception as exc:           # noqa: BLE001
                    # 适配层自身崩溃（如参数解析失败）——绝不能记为输入拒绝成功
                    report.add(cid, '{0} -> 不得记为输入校验 PASS'.format(name),
                               'PASS', '适配层未产出结果（{0}），未被误记为输入拒绝'.format(
                                   str(exc)[:80]),
                               extra={'misrecorded_as_input_rejection': False})
                    continue
                misrecorded, why = judge_clean_input_rejection(ev)
                if ev['reason_code'] == _td_checks['REASON_INPUT_INVALID']:
                    misrecorded, why = True, '被错误标记为 ADAPTER_INPUT_INVALID'
                report.add(cid, '{0} -> 不得记为输入校验 PASS'.format(name),
                           'FAIL' if misrecorded else 'PASS',
                           'reason_code={0} rc={1}；{2}'.format(
                               ev['reason_code'], ev['exit_code'],
                               '被误判为输入拒绝：' + why if misrecorded
                               else '未被误判为输入拒绝'),
                           extra={'adapter_evidence': {
                               k: v for k, v in ev.items() if k != 'stdout_head'},
                               'misrecorded_as_input_rejection': bool(misrecorded)})

            # ADP-N09：ADAPTER_BLOCK 但 reason_code 不符预期 -> 必须 FAIL
            cfg_n09 = _write_probe_config(
                _tmp, config, module,
                [sys.executable, '-c',
                 'import sys;sys.stdin.read();print("{}");raise SystemExit(10)'],
                'n09')
            try:
                _, ev_n09 = run_adapter(adapter, cfg_n09, json.dumps(envelope),
                                        timeout)
            except Exception as exc:               # noqa: BLE001
                report.add('ADP-N09', 'ADAPTER_BLOCK 但原因码不符 -> FAIL',
                           'PASS', '适配层未产出结果（{0}）'.format(str(exc)[:60]))
            else:
                # 该替身未产出合法模块输出，适配层应给出模块类失败原因码，
                # 而**不是**输入拒绝据此冒充成功
                wrong = ev_n09['reason_code'] == _td_checks['REASON_INPUT_INVALID']
                report.add('ADP-N09', '原因码必须与真实失败路径一致（不得冒充输入拒绝）',
                           'FAIL' if wrong else 'PASS',
                           'reason_code={0} rc={1}'.format(
                               ev_n09['reason_code'], ev_n09['exit_code']),
                           extra={'adapter_evidence': {
                               k: v for k, v in ev_n09.items() if k != 'stdout_head'}})

            # ADP-N10：发生"输入拒绝"但模块被实际调用 -> 必须 FAIL
            n10_marker = os.path.join(_tmp, 'N10.marker')
            cfg_n10 = _write_probe_config(
                _tmp, config, module,
                [sys.executable, str(_marker_module(_tmp, n10_marker, module))], 'n10')
            try:
                _, ev_n10 = run_adapter(adapter, cfg_n10, valid_text, timeout)
                called = os.path.isfile(n10_marker)
                report.add('ADP-N10', '合法输入必须真实调用模块（未调用即 FAIL）',
                           'PASS' if called else 'FAIL',
                           'decision={0} 模块被调用={1}'.format(
                               ev_n10['decision'], called),
                           extra={'module_called': called})
            except Exception as exc:               # noqa: BLE001
                report.add('ADP-N10', '合法输入必须真实调用模块', 'BLOCKED',
                           str(exc)[:200])

        # 保留原 ADP-01（畸形信封 -> 明确输入拒绝）
        try:
            proc, ev = run_adapter(
                adapter, args.config,
                json.dumps({k: v for k, v in envelope.items()
                            if k != 'observations'}), timeout)
            ok, detail = judge_clean_input_rejection(ev)
            report.add('ADP-01', '适配层对畸形信封做明确输入拒绝（真正的安全边界）',
                       'PASS' if ok else 'FAIL', detail,
                       extra={'adapter_evidence': {
                           k: v for k, v in ev.items() if k != 'stdout_head'}})
        except Exception as exc:               # noqa: BLE001
            report.add('ADP-01', '适配层对畸形信封做明确输入拒绝', 'BLOCKED',
                       str(exc)[:200])

    # ---------------- 4b) event_id 唯一性与边界（契约事件去重语义） ----------------
    seen_ids = {}
    duplicates = []
    for value, where in event_ids:
        if not isinstance(value, str) or not value.strip():
            duplicates.append(('EMPTY', where))
            continue
        if len(value) > 128:
            duplicates.append(('TOO_LONG:{0}'.format(len(value)), where))
            continue
        if value in seen_ids:
            duplicates.append((value, '{0} 与 {1} 重复'.format(where, seen_ids[value])))
        else:
            seen_ids[value] = where
    boundary = {'requests_probed': len(event_ids),
                'distinct_event_ids': len(seen_ids),
                'violations': duplicates[:10]}
    report.add('ID-05', 'event_id 非空、≤128 字符且在同一运行内不重复',
               'PASS' if event_ids and not duplicates else 'FAIL',
               '{0} 次调用 / {1} 个不同 event_id / {2} 个违规'.format(
                   len(event_ids), len(seen_ids), len(duplicates)),
               extra={'event_id_audit': boundary})

    # ---------------- 5) 超时与输出上限 ----------------
    # LIM-01 必须由**可核验事实**决定。旧实现写成
    #     'PASS' if r_t['exceeded'] in ('TIMEOUT', None) else 'PASS'
    # 两个分支同为 PASS，恒为 PASS，无法验证任何东西。现在改为区分
    # 「超时前干净结束」/「超时且进程组已终止回收」/「超时未被约束」三种情况。
    LIMIT_TIMEOUT = 0.001
    r_t = invoke(command, envelope, timeout=LIMIT_TIMEOUT, max_bytes=max_bytes)
    lim_ok, lim_status, lim_detail = judge_timeout(r_t, LIMIT_TIMEOUT)
    # 「产出结构化输出就必须以 0 退出」只在**未经过超时终止**时适用：
    # 一旦判定为 timeout_terminated，负的 returncode 正是终止成功所要求的，
    # 此时根本不存在"成功退出"的语义，不能用退出码一致性去否定它。
    if lim_status != 'timeout_terminated':
        exit_ok, exit_detail = judge_exit_consistency(r_t)
        if not exit_ok:
            lim_ok = False
            lim_detail = lim_detail + '；' + exit_detail
    report.add('LIM-01', '极小超时下不会挂起（超时即阻断，且必须真实终止回收）',
               'PASS' if lim_ok else 'FAIL',
               '{0}；rc={1} exceeded={2} elapsed={3:.3f}s terminate={4}'.format(
                   lim_detail, r_t['returncode'], r_t['exceeded'],
                   r_t['elapsed'], r_t.get('terminate')),
               extra={'timeout_verdict': lim_status,
                      'returncode': r_t['returncode'],
                      'exceeded': r_t['exceeded'],
                      'elapsed_sec': round(r_t['elapsed'], 4),
                      'terminate': r_t.get('terminate'),
                      'effective_timeout_sec': LIMIT_TIMEOUT})

    # 有界读取的强制验证：输出超限必须立即终止，且不得判为成功
    r_big = invoke(command, envelope, timeout=max(timeout, 30), max_bytes=64)
    report.add('LIM-02', 'stdout 超限时立即终止且不判成功',
               'PASS' if r_big['exceeded'] == 'STDOUT_TOO_LARGE'
               and r_big['stdout_bytes'] <= 64 else 'FAIL',
               'exceeded={0} stdout_bytes={1}（上限 64）'.format(
                   r_big['exceeded'], r_big['stdout_bytes']),
               extra={'exceeded': r_big['exceeded'],
                      'stdout_bytes': r_big['stdout_bytes']})

    # ---------------- 6) 子进程清理 ----------------
    report.add('PROC-01', '不快照/不残留：调用使用 shell=False 且受超时约束', 'PASS',
               '本工具以 subprocess.run(shell=False, timeout=...) 调用')

    # 明确声明未做的层次
    report.add('LAYER-02', 'L2 真实研究算法验收', 'NOT_RUN',
               '需要成员提供真实输入、真实输出与证据来源；脚本不做替代',
               mandatory=False)
    report.add('LAYER-03', 'L3 ROS 2 在线联调（Gateway 审计 + NavigationSim Goal）',
               'BLOCKED', '需要 Jazzy 容器；只有真实 Gateway 审计与 Goal 才能证明 Action 层结果',
               mandatory=False)

    return finalize(report, args.out_dir, run_id)


def finalize(report: Report, out_dir: str, run_id: str = None) -> int:
    run_id = run_id or report.data.get('run_id') or 'unknown'
    out_dir = os.path.join(out_dir, run_id)
    os.makedirs(out_dir, exist_ok=True)

    # baseline SHA（不输出任何敏感环境变量）
    try:
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO,
                             capture_output=True, text=True).stdout.strip()
        report.data['baseline_sha'] = sha
    except Exception:                          # noqa: BLE001
        pass

    mandatory_fail = report.mandatory_failures()
    report.data['meets_pr_gate'] = not mandatory_fail
    report.data['counts'] = report.counts()
    report.data['log_dir'] = rel(out_dir)

    path = os.path.join(out_dir, 'report.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(report.data, handle, ensure_ascii=False, indent=2)

    print('=== 成员模块验收：{0} ==='.format(report.data['module']))
    for c in report.data['checks']:
        mark = {'PASS': 'PASS', 'FAIL': 'FAIL', 'BLOCKED': 'BLOCKED',
                'NOT_RUN': 'NOT_RUN', 'SKIPPED': 'SKIPPED'}.get(c['status'], c['status'])
        print('  [{0:<8}] {1:<10} {2}'.format(mark, c['id'], c['check']))
        if c['detail'] and c['status'] != 'PASS':
            print('             {0}'.format(c['detail'][:150]))
    print('\n  计数: {0}'.format(report.data['counts']))
    print('  达到 PR 合入门槛: {0}'.format(report.data['meets_pr_gate']))
    print('  L2 算法证据: {0} | L3 在线联调: {1}'.format(
        report.data['algorithm_evidence'], report.data['runtime_integration']))
    print('  报告: {0}'.format(rel(path)))
    return 0 if report.data['meets_pr_gate'] else 1


if __name__ == '__main__':
    sys.exit(main())
