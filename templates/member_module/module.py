#!/usr/bin/env python3
"""成员研究模块工程模板 —— RosSystem F0 外部模块协议。

复制本文件到你的模块目录后，只需替换 `analyse()` 的实现。

协议（与 mock_modules/*_mock.py 完全一致，因此适配层无需改动）
--------------------------------------------------------------
  输入：stdin  一个 ModuleInputEnvelope（JSON）
  输出：stdout 一个研究输出（JSON）—— **只能有一个 JSON 对象**
  诊断：stderr （绝不污染 stdout）

支持三种模块身份
----------------
  comm_risk       -> CommRiskEvidence        允许推进状态 NORMAL
  identity_trust  -> IdentityTrustAssessment 允许推进状态 AUTHORIZED
  task_risk       -> TaskRiskDecision        允许推进状态 ALLOW_RECOMMENDED

安全默认行为（本模板最重要的约束）
----------------------------------
**默认只能安全失败，不能默认放行。**

  * 未接入真实算法时，**不输出**虚构的 NORMAL / AUTHORIZED / ALLOW_RECOMMENDED；
  * 不伪造权限文件、DDS 日志或真实攻击观测；
  * 不把 `producer.source = EXTERNAL` 解释为"已完成身份验证"；
  * 无法形成合法且真实的字段映射时，**以非零退出码失败**，
    由适配层安全阻断 —— 宁可阻断，也不填虚构字段。

禁止事项
--------
  * 不使用 `shell=True`；
  * 不从业务 JSON 读取待执行命令；
  * 不从不可信输入选择 joblib 模型；
  * 不修改全局 DDS 权限；
  * 不绕过 Gateway；
  * 不直接向 `/rg/nav_execute` 发送任何内容。
"""

from __future__ import annotations

import argparse
import json
import sys

MODULE_DIR = None  # 由 init 工具或你手工设置（用于定位仓库根）；保持 None 也可运行

SCHEMA_VERSION = '1.0.0-proposed'

#: 每个模块身份的固定元数据。**不要**从业务输入读取这些值。
MODULE_SPEC = {
    'comm_risk': {
        'schema': 'comm_risk_evidence',
        'proceed_state': 'NORMAL',
        'block_state': 'SUSPICIOUS',
        'unknown_state': 'UNKNOWN',
        'error_state': 'ERROR',
        'event_suffix': 'comm',
    },
    'identity_trust': {
        'schema': 'identity_trust_assessment',
        'proceed_state': 'AUTHORIZED',
        'block_state': 'DENIED',
        'unknown_state': 'UNKNOWN',
        'error_state': 'ERROR',
        'event_suffix': 'identity',
    },
    'task_risk': {
        'schema': 'task_risk_decision',
        'proceed_state': 'ALLOW_RECOMMENDED',
        'block_state': 'BLOCK_RECOMMENDED',
        'unknown_state': 'UNKNOWN',
        'error_state': 'ERROR',
        'event_suffix': 'taskrisk',
    },
}

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_NO_ALGORITHM = 3
EXIT_INTERNAL_ERROR = 4


def note(message: str) -> None:
    """诊断信息一律写 stderr。"""
    print('[module] {0}'.format(message), file=sys.stderr)


def read_envelope() -> dict:
    """严格解析 stdin 的单个 JSON 对象。"""
    raw = sys.stdin.read()
    if not raw.strip():
        note('stdin 为空，期望一个 ModuleInputEnvelope JSON')
        sys.exit(EXIT_INPUT_ERROR)
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        note('stdin 不是合法 JSON: {0}'.format(exc))
        sys.exit(EXIT_INPUT_ERROR)
    if not isinstance(payload, dict):
        note('信封顶层必须是 JSON 对象，实际为 {0}'.format(type(payload).__name__))
        sys.exit(EXIT_INPUT_ERROR)
    return payload


def check_envelope(envelope: dict) -> dict:
    """校验信封的必要字段并返回关联标识。"""
    version = envelope.get('schema_version')
    if version != SCHEMA_VERSION:
        note('schema_version 不匹配：期望 {0!r}，实际 {1!r}'.format(
            SCHEMA_VERSION, version))
        sys.exit(EXIT_INPUT_ERROR)
    run_id = envelope.get('run_id')
    request_id = envelope.get('request_id')
    if not run_id or not request_id:
        note('信封缺少 run_id 或 request_id（二者都用于关联与审计）')
        sys.exit(EXIT_INPUT_ERROR)
    if not isinstance(envelope.get('observations'), list) or not envelope['observations']:
        note('信封缺少 observations（没有可用观测，无法形成真实判断）')
        sys.exit(EXIT_INPUT_ERROR)
    return {
        'run_id': run_id,
        'request_id': request_id,
        'observed_at': envelope.get('created_at') or '',
        'candidate_action': envelope.get('candidate_action') or {},
    }


# ===========================================================================
# 你的算法在这里
# ===========================================================================
def analyse(module: str, envelope: dict, context: dict):
    """**占位实现：默认不产生任何真实判断。**

    返回 (state, detail_dict)。

    * 返回 `None` 表示"本模板尚未接入真实算法" —— 调用方会以
      退出码 3 安全失败，由适配层阻断。**这是刻意的默认行为。**
    * 接入真实算法后，请返回 MODULE_SPEC 中该模块的合法状态值之一。

    替换示例（成员一，通信模块）::

        def analyse(module, envelope, context):
            features = extract_features(envelope)      # 你自己的特征提取
            if features is None:
                return 'UNKNOWN', {'reason': 'FEATURES_ABSENT'}
            score = my_model.predict(features)          # 你自己的真实算法
            state = 'NORMAL' if score < threshold else 'SUSPICIOUS'
            return state, {'score': score, 'model_sha256': MY_MODEL_SHA256}

    注意：**不要**用硬编码标签、预设 allow 或直接返回 Mock 结果来冒充研究成果。
    """
    return None


def build_output(module: str, context: dict, state: str, detail: dict) -> dict:
    """按模块身份组装符合对应 Schema 的输出。

    只填**能真实产生**的字段；不确定的字段不填，不编造默认值。
    """
    spec = MODULE_SPEC[module]
    action = context['candidate_action']
    output = {
        'schema_version': SCHEMA_VERSION,
        'run_id': context['run_id'],
        'request_id': context['request_id'],
        'event_id': 'evt-{0}-{1}'.format(spec['event_suffix'], context['request_id']),
        # EXTERNAL 只表示"这是一个真实外部模块"，**不代表已完成任何身份验证**
        'producer': {
            'name': '{0}_module'.format(module),
            'module_version': '0.1.0',
            'source': 'EXTERNAL',
        },
        'observed_at': context['observed_at'],
        'status': state,
        'reason': detail.get('reason', ''),
        'evidence_refs': [{
            'ref': detail.get('evidence_ref', 'templates/member_module/module.py'),
            'kind': detail.get('evidence_kind', 'UNKNOWN'),
            'note': ('由成员模块产生；本模板默认不接入真实算法，'
                     '因此该证据不构成任何安全保证。'),
        }],
    }
    # 只有模块确实产生了对应字段时才填，避免编造
    for key in ('anomaly_category', 'risk_level', 'communication',
                'window', 'request_count', 'frequency_hz', 'basis',
                'identity', 'trust_level', 'task', 'policy_ref'):
        if key in detail:
            output[key] = detail[key]
    if action.get('action_resource'):
        output.setdefault('communication', {})['resource'] = action['action_resource']
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description='RosSystem 成员研究模块模板')
    parser.add_argument('--module', required=True, choices=sorted(MODULE_SPEC),
                        help='模块身份（决定输出 Schema 与状态枚举）')
    parser.add_argument('--log', default=None, help='可选：运行诊断日志路径')
    parser.add_argument('--allow-placeholder', action='store_true',
                        help='仅用于模板自测：允许占位实现输出合法 UNKNOWN；'
                             '**不得**在真实研究中用它冒充算法成果')
    args = parser.parse_args(argv)

    if args.module not in MODULE_SPEC:
        note('未知模块: {0}'.format(args.module))
        return EXIT_INPUT_ERROR

    envelope = read_envelope()
    context = check_envelope(envelope)

    try:
        result = analyse(args.module, envelope, context)
    except Exception as exc:                  # noqa: BLE001
        note('算法执行异常: {0}: {1}'.format(type(exc).__name__, exc))
        # 用语义诚实的 ERROR 状态输出（结构合法、状态不推进）
        output = build_output(args.module, context,
                              MODULE_SPEC[args.module]['error_state'],
                              {'reason': '模块内部异常，未能形成判断'})
        sys.stdout.write(json.dumps(output, ensure_ascii=False) + '\n')
        return EXIT_OK

    if result is None:
        if args.allow_placeholder:
            # 语义诚实：UNKNOWN 表示"无法判定"，**不表示正常**
            output = build_output(
                args.module, context, MODULE_SPEC[args.module]['unknown_state'],
                {'reason': ('模板占位实现尚未接入真实算法，'
                            '无法判定（UNKNOWN 不等于允许推进）'),
                 'evidence_kind': 'UNKNOWN'})
            sys.stdout.write(json.dumps(output, ensure_ascii=False) + '\n')
            if args.log:
                with open(args.log, 'a', encoding='utf-8') as handle:
                    handle.write(json.dumps(output, ensure_ascii=False) + '\n')
            return EXIT_OK
        note('模板尚未接入真实算法。**不会**输出虚构的 NORMAL/AUTHORIZED/'
             'ALLOW_RECOMMENDED。请实现 analyse() 后重试；'
             '若仅用于协议自测，可加 --allow-placeholder。')
        return EXIT_NO_ALGORITHM

    state, detail = result
    legal = {MODULE_SPEC[args.module][k] for k in
             ('proceed_state', 'block_state', 'unknown_state', 'error_state')}
    if state not in legal:
        note('算法返回了非法状态 {0!r}；本模块允许的状态为 {1}'.format(
            state, sorted(legal)))
        return EXIT_INTERNAL_ERROR

    output = build_output(args.module, context, state, detail)
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + '\n')
    if args.log:
        with open(args.log, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(output, ensure_ascii=False) + '\n')
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
