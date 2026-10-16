#!/usr/bin/env python3
"""Fail-closed SROS2 permission and controlled-experiment evidence assessor.

This component is an advisory evidence interpreter; it neither authenticates a
live DDS participant nor changes any DDS permissions/Gateway decisions.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0'
CONTRACT = '1.0.0-proposed'
ENTRY = '/rg/guarded_navigate'
EXECUTE = '/rg/nav_execute'
CASES = {
    'S2': ('/planner', 'planner_node', ENTRY, 'AUTHORIZED', 'planner.log'),
    'S3C': ('/gateway', 'security_gateway', EXECUTE, 'AUTHORIZED', 'rogue_gateway.log'),
    'S3': ('/planner', 'planner_node', EXECUTE, 'DENIED', 'rogue_planner.log'),
    'S4': ('/unauthorized', 'rogue_client', EXECUTE, 'DENIED', 'rogue_unauthorized.log'),
}
SAFE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')

# --------------------------------------------------------------------------
# ANSI 规范化（有界）
# --------------------------------------------------------------------------
# 真实 Fast DDS 拒绝日志由终端着色输出写入文件，控制序列会**插进**
# 「SECURITY Error」字样内部，例如：
#   ESC[31;1m[ ESC[37;1mSECURITY ESC[31;1m Error] ESC[37mrr/... not found in allow rule
# 因此必须先做有界规范化，再做语义匹配。此处只做「删除 + 行内匹配」，
# 不做任何通配、模糊或跨行拼接匹配。
#
# 正规 ANSI 转义序列文法：
#   ESC [ <参数字节 0x30-0x3F>* <中间字节 0x20-0x2F>* <终止字节 0x40-0x7E>
#   ESC <单字符>                      （如 ESC ( B、ESC = 等双字符序列）
#   ESC ] ... (BEL | ESC \)           （OSC 字符串）
ANSI_CSI_RE = re.compile('\x1b\\[[0-?]*[ -/]*[@-~]')
ANSI_TWO_CHAR_RE = re.compile('\x1b[@-Z\\\\-_]')
ANSI_OSC_RE = re.compile('\x1b\\][^\x07\x1b]*(?:\x07|\x1b\\\\)')
#: 规范化后仍然残留的 C0/C1 控制字符（制表符除外）视为格式不可信。
RESIDUAL_CTRL_RE = re.compile('[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]')
MAX_NATIVE_DENIAL_LINE = 1200

#: 原生 Fast DDS 访问控制拒绝的**行内**语义签名。
#: 只要求「SECURITY ... Error]」「not found in allow rule」「Permissions.cpp:」，
#: 不绑定具体函数名（datareader/writer 两条路径都会出现）。
NATIVE_DENIAL_LINE_RE = re.compile(
    r'SECURITY[^A-Za-z0-9]{0,4}Error\s*\][^\n]{0,600}?not found in allow rule'
    r'[^\n]{0,300}?Permissions\.cpp:\d+', re.I)
#: 行内出现的 DDS 主题名（资源）。用于核对「拒绝资源」与场景期望资源。
TOPIC_IN_LINE_RE = re.compile(r'\b((?:rq|rr|rt)/[A-Za-z0-9_./-]+)')
#: 客户端自报的失败类别。只有原生拒绝类别才可能对应 DDS 访问控制。
NATIVE_DENIAL_OUTCOMES = ('ACTION_CLIENT_CREATION_DENIED', 'EXCEPTION',
                          'NODE_CREATION_FAILED')
#: 明确**不是** DDS 拒绝的类别：超时、服务端不可达、业务阻断、普通异常。
NON_DDS_OUTCOMES = ('SEND_GOAL_TIMEOUT', 'RESULT_TIMEOUT',
                    'GOAL_ACCEPTANCE_TIMEOUT', 'NO_ACTION_SERVER',
                    'ACTION_SERVER_UNREACHABLE', 'GOAL_REJECTED', 'TIMEOUT',
                    'BLOCKED_BY_TASK_POLICY', 'POLICY_BLOCK')
#: 客户端结果中若出现这些业务策略标记，则一律不得判为 DDS 权限拒绝。
BUSINESS_POLICY_MARKERS = ('OUT_OF_REGION', 'TASK_MISMATCH', 'DUPLICATE_REQUEST',
                           'RATE_LIMIT', 'POLICY_MISSING')
BROAD = {'*', '/*', 'rt/*', 'rq/*Request', 'rr/*Reply'}


def local(tag):
    return tag.rsplit('}', 1)[-1]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def strict_json(raw):
    def obj(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError('duplicate JSON key: ' + k)
            result[k] = v
        return result

    def reject(x):
        raise ValueError('nonfinite JSON number: ' + x)

    return json.loads(raw, object_pairs_hook=obj, parse_constant=reject)


def envelope_check(e):
    if not isinstance(e, dict) or e.get('schema_version') != CONTRACT:
        raise ValueError('incompatible input schema/version')
    for key in ('run_id', 'request_id', 'created_at'):
        if not isinstance(e.get(key), str) or not e[key]:
            raise ValueError('missing/invalid ' + key)
    for key in ('run_id', 'request_id'):
        if len(e[key]) > 128:
            raise ValueError('oversized ' + key)
    action = e.get('candidate_action', {})
    if not isinstance(action, dict) or action.get('action_resource') != ENTRY or action.get('operation') != 'NAVIGATE':
        raise ValueError('candidate action must use guarded_navigate NAVIGATE')
    if not isinstance(e.get('observations'), list) or not e['observations'] or not isinstance(e.get('evidence_refs'), list) or not e['evidence_refs']:
        raise ValueError('missing observations/evidence_refs')
    # When running within RosSystem, also validate the exact unmodified public schema.
    # A standalone source-only unit fixture (without the full repository) uses
    # minimal checks above; team_demo always validates both input and output.
    schema = ROOT / 'docs/interfaces/schemas/module_input.schema.json'
    if schema.is_file():
        try:
            import jsonschema
            jsonschema.Draft202012Validator(
                json.loads(schema.read_text(encoding='utf-8')),
                format_checker=jsonschema.FormatChecker()).validate(e)
        except Exception as exc:  # adapter will also enforce schema independently
            raise ValueError('official ModuleInputEnvelope validation failed: ' + str(exc)) from exc


def tree(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('missing or unsafe XML: ' + str(path))
    if path.stat().st_size > 2_000_000:
        raise ValueError('oversized XML')
    raw = path.read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('unsafe XML declaration')
    return ET.fromstring(raw)


def policy_permits(policy, enclave, service):
    root = tree(policy)
    if local(root.tag) != 'policy':
        raise ValueError('invalid SROS policy root')
    matches = [n for n in root.iter() if local(n.tag) == 'enclave' and n.get('path') == enclave]
    if len(matches) != 1:
        raise ValueError('missing/duplicated enclave policy ' + enclave)
    # No implicit wildcard: a malformed/wide-open policy must not be reported safe.
    for elem in root.iter():
        if local(elem.tag) in ('topic', 'service') and any(x in (elem.text or '') for x in ('*', '?')):
            raise ValueError('wildcard in SROS policy')
    for profile in matches[0]:
        if local(profile.tag) != 'profiles':
            continue
        for node in profile:
            if local(node.tag) != 'profile':
                continue
            for collection in node:
                if local(collection.tag) != 'services' or collection.get('request') != 'ALLOW':
                    continue
                if any(local(s.tag) == 'service' and (s.text or '').strip() == service for s in collection):
                    return root.get('version'), True
    return root.get('version'), False


def permission_permits(path, service, domain=43):
    """Inspect *generated* DDS permissions.xml, not the policy source alone.

    DDS service request = publish rq/<service>Request and subscribe
    rr/<service>Reply. Check both directions under the same allow_rule.
    """
    root = tree(path)
    grants = [e for e in root.iter() if local(e.tag) == 'grant']
    if len(grants) != 1:
        raise ValueError('expected one DDS permission grant')
    grant = grants[0]
    defaults = [(x.text or '').strip().upper() for x in grant if local(x.tag) == 'default']
    if defaults != ['DENY']:
        raise ValueError('DDS permissions must be default DENY')
    if not any(local(x.tag) == 'subject_name' and (x.text or '').strip()
               for x in grant):
        raise ValueError('DDS permissions missing subject_name')
    allowed = []
    domains = set()
    for rule in grant.iter():
        if local(rule.tag) == 'id' and (rule.text or '').strip().isdigit():
            domains.add(int(rule.text.strip()))
        if local(rule.tag) != 'allow_rule':
            continue
        pub, sub = set(), set()
        for direction in rule:
            if local(direction.tag) not in ('publish', 'subscribe'):
                continue
            for topic in direction.iter():
                if local(topic.tag) == 'topic' and topic.text:
                    name = topic.text.strip()
                    if '*' in name or '?' in name or name in BROAD:
                        raise ValueError('DDS permission contains wildcard/broad allow')
                    (pub if local(direction.tag) == 'publish' else sub).add(name)
        allowed.append((pub, sub))
    if domains != {domain}:
        raise ValueError('DDS permission domain mismatch or missing domain')
    prefix = service.lstrip('/')
    req, rep = 'rq/' + prefix + 'Request', 'rr/' + prefix + 'Reply'
    return any(req in pub and rep in sub for pub, sub in allowed)


def evidence_ref(path):
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def read_summary(evidence_root, experiment_run):
    if not SAFE_NAME.fullmatch(experiment_run):
        raise ValueError('invalid experiment run ID')
    base = evidence_root.resolve() / experiment_run
    if not base.resolve().is_relative_to(evidence_root.resolve()) or base.is_symlink():
        raise ValueError('unsafe evidence path')
    summary_path = base / 'summary.json'
    if summary_path.is_symlink() or not summary_path.is_file() or summary_path.stat().st_size > 2_000_000:
        raise ValueError('missing/unsafe summary')
    summary = strict_json(summary_path.read_text(encoding='utf-8'))
    if (summary.get('suite') != 'sros2' or summary.get('run_id') != experiment_run
            or str(summary.get('secure_domain')) != '43' or summary.get('failed') != 0):
        raise ValueError('summary is not a passing domain-43 SROS2 experiment')
    cases = summary.get('scenarios')
    if not isinstance(cases, list) or len(cases) != len({s.get('scenario_id') for s in cases if isinstance(s, dict)}):
        raise ValueError('invalid/duplicate experiment cases')
    return base, {x['scenario_id']: x for x in cases}, evidence_ref(summary_path)


def checked_case(cases, case_id, expected_resource, expected_enclave, goals):
    c = cases.get(case_id)
    if not isinstance(c, dict) or c.get('result') != 'PASS' or c.get('status') != 'PASS' or c.get('security_mode') != 'enforce':
        raise ValueError(case_id + ' not PASS under Enforce')
    if c.get('source_enclave') != expected_enclave or c.get('requested_resource') != expected_resource or c.get('downstream_goal_count') != goals:
        raise ValueError(case_id + ' reported inconsistent enclave/resource/goal count')
    if not isinstance(c.get('checks'), list) or not c['checks'] or any(v.get('result') != 'PASS' for v in c['checks']):
        raise ValueError(case_id + ' failed validation checks')
    return c


def read_case_log(base, case_id, filename):
    path = base / case_id / filename
    if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()) or not path.is_file() or path.stat().st_size > 3_000_000:
        raise ValueError('missing/unsafe case log: ' + str(path))
    return path.read_text(encoding='utf-8', errors='replace'), evidence_ref(path)


def log_result(log, prefix):
    lines = [line[len(prefix):] for line in log.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise ValueError('missing/duplicate log result ' + prefix)
    value = strict_json(lines[0])
    if not isinstance(value, dict):
        raise ValueError('malformed log result')
    return value


def normalize_ansi(text):
    """有界地把终端着色日志规范化成纯文本。

    只做转义序列删除，不做大小写折叠、不做空白重排、不跨行拼接。
    返回 (规范化文本, 统计信息)。残留控制字符会如实计数，由调用方决定是否失败关闭。
    原始日志文件从不被改写 —— 规范化只发生在内存中。
    """
    raw_len = len(text)
    counts = {'csi': 0, 'osc': 0, 'two_char': 0, 'residual_ctrl': 0}
    if '\x1b' not in text:
        counts['had_escapes'] = False
        return text, counts
    counts['had_escapes'] = True
    for key, pattern in (('osc', ANSI_OSC_RE), ('csi', ANSI_CSI_RE),
                         ('two_char', ANSI_TWO_CHAR_RE)):
        text, n = pattern.subn('', text)
        counts[key] = n
    counts['residual_ctrl'] = len(RESIDUAL_CTRL_RE.findall(text))
    counts['raw_chars'] = raw_len
    counts['normalized_chars'] = len(text)
    return text, counts


def native_denial_line(line):
    """判断单行是否为原生 Fast DDS 访问控制拒绝，返回行内 DDS 主题名。

    严格条件（全部必须在**同一行**内成立）：
      1. ``SECURITY ... Error]`` 与 ``not found in allow rule`` 同时出现；
      2. 出现 ``Permissions.cpp:<行号>`` 原生源码位置；
      3. 行内能抽出一个 DDS 主题名（资源），供调用方核对。

    不做跨行匹配，因此「SECURITY Error」出现在一行、而「not found in allow rule」
    出现在另一行时不会被拼接成拒绝证据。
    """
    if len(line) > MAX_NATIVE_DENIAL_LINE:
        return None
    if not NATIVE_DENIAL_LINE_RE.search(line):
        return None
    topic = TOPIC_IN_LINE_RE.search(line)
    return topic.group(1) if topic else None


def native_denial_records(log):
    """返回规范化日志中所有原生拒绝行：[(行号, 行原文, DDS 主题名)]。"""
    normalized, _stats = normalize_ansi(log)
    records = []
    for index, line in enumerate(normalized.splitlines(), start=1):
        topic = native_denial_line(line)
        if topic is not None:
            records.append((index, line.strip()[:MAX_NATIVE_DENIAL_LINE], topic))
    return records


def expected_denial_topics(resource):
    """场景期望资源对应的 DDS 主题名。

    Action 服务请求 = publish ``rq/<svc>Request``；Action 服务应答 =
    subscribe ``rr/<svc>Reply``。二者同属该资源的访问控制判定，
    但任一方向都必须是**同一资源** —— 别的资源一律不算。
    """
    service = resource.rstrip('/') + '/_action/send_goal'
    prefix = service.lstrip('/')
    return {'rq/' + prefix + 'Request', 'rr/' + prefix + 'Reply'}


def dds_denial_evidence(log, resource, observed):
    """核对「拒绝资源 + 拒绝场景 + 原生权限错误」三者对应关系。

    任一项不成立即抛 ValueError（调用方失败关闭）。**不允许**把客户端超时、
    Action Server 不可达、业务 TaskPolicy 阻断或普通异常当作 DDS 权限拒绝。
    """
    outcome = observed.get('outcome')
    if outcome in NON_DDS_OUTCOMES:
        raise ValueError('client outcome {0!r} is not a DDS access-control denial'.format(outcome))
    if outcome not in NATIVE_DENIAL_OUTCOMES:
        raise ValueError('client outcome {0!r} is not a native denial class'.format(outcome))
    # 业务策略阻断即使伴随原生报错，也不是「资源未被允许」的语义。
    blob = json.dumps(observed, ensure_ascii=False, sort_keys=True)
    for marker in BUSINESS_POLICY_MARKERS:
        if marker in blob:
            raise ValueError('client outcome reports business policy {0}, not DDS ACL'.format(marker))
    records = native_denial_records(log)
    if not records:
        raise ValueError('no native access-control denial in client log')
    expected = expected_denial_topics(resource)
    matched = [record for record in records if record[2] in expected]
    if not matched:
        observed_topics = sorted({record[2] for record in records})
        raise ValueError(
            'native denial resource {0} does not match expected resource {1}'.format(
                observed_topics, sorted(expected)))
    line_no, line, topic = matched[0]
    return {'resource_topic': topic, 'line_number': line_no, 'line': line,
            'matched_records': len(matched), 'total_records': len(records)}


def examine(policy, keystore, evidence_root, run_id, case_id):
    enclave, node, action, expected, logname = CASES[case_id]
    service = action + '/_action/send_goal'
    version, source_allowed = policy_permits(policy, enclave, service)
    permission = keystore / 'enclaves' / enclave.strip('/') / 'permissions.xml'
    generated_allowed = permission_permits(permission, service)
    if source_allowed != generated_allowed:
        raise ValueError('policy and generated DDS permission disagree')
    if source_allowed != (expected == 'AUTHORIZED'):
        raise ValueError('configuration inconsistent with controlled test outcome')
    base, cases, summary_ref = read_summary(evidence_root, run_id)
    checked_case(cases, case_id, action, enclave, 1 if expected == 'AUTHORIZED' else 0)
    log, ref = read_case_log(base, case_id, logname)
    controls = []
    denial = None
    if case_id == 'S2':
        observed = log_result(log, 'PLANNER_RESULT ')
        if observed.get('success') is not True or observed.get('status_code') != 'EXECUTED':
            raise ValueError('S2 lacks successful planner execution')
    else:
        observed = log_result(log, 'ROGUE_RESULT ')
        if observed.get('target_action') != action or observed.get('node_name') != node:
            raise ValueError('rogue-client log target/node mismatch')
        if case_id == 'S3C':
            if observed.get('outcome') != 'RESULT' or observed.get('success') is not True or observed.get('status_code') != 'EXECUTED':
                raise ValueError('S3C success not shown in raw client log')
        else:
            # 原生 DDS 报错文本是必要条件（TIMEOUT 本身永远不是 DDS 拒绝）；
            # 同时必须核对拒绝资源、拒绝场景与原生权限错误的对应关系。
            denial = dds_denial_evidence(log, action, observed)
            checked_case(cases, 'S3C', EXECUTE, '/gateway', 1)
            control_log, control_ref = read_case_log(base, 'S3C', 'rogue_gateway.log')
            control = log_result(control_log, 'ROGUE_RESULT ')
            if control.get('target_action') != EXECUTE or control.get('outcome') != 'RESULT' or control.get('success') is not True or control.get('status_code') != 'EXECUTED':
                raise ValueError('S3C positive control missing for native denial')
            controls.append(control_ref)
    return {'status': expected, 'subject_name': node, 'declared_enclave': enclave,
            'resource': action, 'policy_version': version, 'source_ref': evidence_ref(policy), 'summary_ref': summary_ref,
            'log_ref': ref, 'permissions_ref': evidence_ref(permission), 'control_refs': controls,
            'denial': denial['line'][-300:] if denial else None,
            'denial_topic': denial['resource_topic'] if denial else None,
            'denial_line': denial['line_number'] if denial else None}


def assessment(envelope, args):
    envelope_check(envelope)
    case_id = args.case
    enclave, node, action, _expected, _logname = CASES[case_id]
    current_resource = envelope['candidate_action']['action_resource']
    status, detail = 'UNKNOWN', None
    binding = 'UNBOUND_NO_CURRENT_REQUEST_SUBJECT'
    reason = '未获得可验证的权限与运行时证据'
    try:
        if not args.experiment_run:
            raise ValueError('no trusted experiment run pinned by process configuration')
        detail = examine(Path(args.policy), Path(args.keystore), Path(args.evidence_root), args.experiment_run, case_id)
        status = detail['status']
        # ------------------------------------------------------------------
        # 历史受控实验结论只对**它当时访问的那个资源**成立，而且只对该次
        # 运行中真实使用 DDS 身份的主体成立。它既不证明「当前候选任务对应的
        # 通信主体已通过 DDS 认证」，也不证明当前请求的资源已被判定。
        # 因此这里必须显式比较历史资源与当前候选资源，绝不把执行端
        # (/rg/nav_execute) 的历史判定搬到 guarded Action (/rg/guarded_navigate) 上。
        # ------------------------------------------------------------------
        if detail['resource'] != current_resource:
            status = 'UNKNOWN'
            binding = 'HISTORICAL_RESOURCE_MISMATCH'
            reason = ('历史受控实验证据针对资源 {0}（{1}），与当前候选资源 {2} 不同；'
                      '该历史判定不能解释当前请求，且当前请求缺少与已认证 DDS 主体的绑定'
                      ).format(detail['resource'], detail['status'], current_resource)
        else:
            binding = 'HISTORICAL_RESOURCE_MATCHES_CURRENT'
            reason = ('受控 DDS Enforce 实验及本地权限文件一致，观察到原生访问控制拒绝（且正向对照成功）'
                      if status == 'DENIED' else
                      '受控 DDS Enforce 实验及本地权限文件一致，观察到授权通信成功'
                      if status == 'AUTHORIZED' else
                      '受控 DDS Enforce 实验未给出可推进结论')
    except (ValueError, OSError, ET.ParseError, KeyError, TypeError) as exc:
        reason = '证据不足或不可核验，失败关闭：' + str(exc)[:420]
        print('[identity_trust] ' + reason, file=sys.stderr)

    item = {
        'schema_version': CONTRACT, 'run_id': envelope['run_id'], 'request_id': envelope['request_id'],
        # event_id 必须能与 request_id 关联：与 modules/member3_taskrisk 的既有约定
        # 保持一致（'<前缀>-<request_id[:80]>-<uuid>'），总长 <= Schema 的 128 上限。
        # 注意契约张力：当 request_id 长度超过 102 字符时，「含完整 request_id」
        # 与「event_id <= 128」无法同时成立（见报告「遗留问题」R-1）。
        'event_id': 'evt-identity-{0}-{1}'.format(envelope['request_id'][:80],
                                                  uuid.uuid4().hex[:24]),
        'producer': {'name': 'identity_trust_assessor', 'module_version': VERSION, 'source': 'EXTERNAL'},
        'observed_at': utc_now(), 'status': status, 'reason': reason[:512],
        'subject': {'observed_name': node, 'declared_enclave': enclave},
        'requested_resource': {'resource': current_resource, 'operation': 'SERVICE_REQUEST'},
        'authorization': {'result_status': status,
                          'denial_layer': 'DDS_ACCESS_CONTROL' if status == 'DENIED' else
                                          ('NONE' if status == 'AUTHORIZED' else 'UNKNOWN')},
        'identity_evidence': {'kind': 'CONTROLLED_SECURITY_EXPERIMENT' if detail else 'UNKNOWN',
                              'detail': ('历史受控实验证据；不证明当前请求的 DDS 身份认证，'
                                         '也不证明当前候选资源已被判定') if detail
                              else '未获得可验证的权限与运行时证据'},
        'access_control_evidence': {'kind': 'NATIVE_ACCESS_CONTROL_LOG' if status == 'DENIED' else ('NONE' if detail else 'UNKNOWN')},
        'evidence_refs': [],
        'extensions': {'experiment_case_id': case_id, 'historical_only': True,
                       'current_request_binding': binding,
                       'historical_experiment_resource': action,
                       'current_candidate_resource': current_resource,
                       'identity_binding_note': ('历史实验只覆盖该次运行中真实使用 DDS 身份的主体；'
                                                 'request_id / declared_enclave / 业务 JSON 自报身份'
                                                 '都不是 DDS 已认证身份')},
    }
    if detail:
        if detail['denial']:
            item['authorization']['denial_detail'] = detail['denial'][:512]
            item['access_control_evidence']['detail'] = detail['denial'][:512]
            item['extensions']['historical_denial_topic'] = detail['denial_topic']
            item['extensions']['historical_denial_log_line'] = detail['denial_line']
        item['policy_ref'] = {'permissions_ref': detail['permissions_ref']}
        if detail['policy_version']:
            item['policy_ref']['policy_version'] = detail['policy_version']
        item['extensions']['experiment_run_id'] = args.experiment_run
        item['extensions']['historical_experiment_status'] = detail['status']
        if case_id == 'S3C':
            item['extensions']['positive_control_verified'] = True
        item['evidence_refs'] = [
            {'ref': detail['summary_ref'], 'kind': 'CONTROLLED_SECURITY_EXPERIMENT'},
            {'ref': detail['log_ref'], 'kind': 'RUNTIME_LOG'},
            {'ref': detail['source_ref'], 'kind': 'PERMISSION_FILE_ANALYSIS'},
            {'ref': detail['permissions_ref'], 'kind': 'PERMISSION_FILE_ANALYSIS'},
        ] + [{'ref': x, 'kind': 'CONTROLLED_SECURITY_EXPERIMENT'} for x in detail['control_refs']]
    else:
        item['evidence_refs'] = [{'ref': 'identity_trust/assessor.py', 'kind': 'UNKNOWN',
                                  'note': '权限/实验证据不可用，不能当作授权证明'}]
    return item


def main(argv=None):
    p = argparse.ArgumentParser(description='Member 2 DDS permission trust assessment (advisory)')
    p.add_argument('--policy', default=str(ROOT / 'security/policies/minimal_permissions.xml'))
    p.add_argument('--keystore', default=str(ROOT / 'security/keystore'))
    p.add_argument('--evidence-root', default=str(ROOT / 'tests/evidence'))
    p.add_argument('--experiment-run', help='受信任本地配置指定的 SROS2 实验运行 ID（不从 stdin 读取）')
    p.add_argument('--case', choices=CASES, default='S2', help='待审阅的受控安全实验场景')
    args = p.parse_args(argv)
    try:
        inp = strict_json(sys.stdin.read())
        doc = assessment(inp, args)
    except (ValueError, TypeError, KeyError) as exc:
        print('[identity_trust] invalid input: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(doc, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
