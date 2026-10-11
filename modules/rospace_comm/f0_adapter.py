#!/usr/bin/env python3
"""f0_adapter.py -- 把 ROSPaCe 检测模型接成 F0 外部模块（阶段 F）。

协议
----
输入：`ModuleInputEnvelope`（stdin，一个 JSON 对象）
输出：`CommRiskEvidence`（stdout，一个 JSON 对象）
与 `mock_modules/comm_risk_mock.py` 完全一致，因此适配层无需改动。

字段语义的诚实边界（**本模块最重要的设计约束**）
------------------------------------------------
ROSPaCe 的特征是**分组/系统级监测值**，不是 ROS 2 业务事件。因此：

| CommRiskEvidence 字段 | 能否由 ROSPaCe 模型真实产生 |
| --- | --- |
| `communication.resource` | **能** —— 取自信封的 `candidate_action.action_resource` |
| `communication.resource_type` | **能** —— 由资源的操作类型推导 |
| `window` | **能** —— 取自信封的时间戳 |
| `request_count` | **不能** —— ROSPaCe 是逐包/逐窗口监测，没有"业务请求"概念 |
| `anomaly_category` | **能** —— 模型预测（是模型输出，不是 DDS 事实） |
| `risk_level` | **能** —— 由模型输出映射（同上） |
| `basis` | **能** —— 记录模型版本与特征来源 |
| `evidence_refs` | **能** —— 证据引用已标注为离线数据集 |

`request_count` 的处理：**不猜、不填 0、不用均值**。只接受来自信封的
`observations[].detail.f0_runtime.request_count`，即由**真实运行侧**提供的
业务请求计数。若信封未提供，模块**拒绝产出完整 CommRiskEvidence** 并以
`ERROR` 状态安全失败（退出码非 0），而不是伪造一个数字。
这正是本模块把 F0 完整接口映射标为 `BLOCKED` 的原因。
"""

from __future__ import annotations

import json
import os
import sys

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, MODULE_DIR)

SCHEMA_VERSION = '1.0.0-proposed'
PRODUCER = {
    'name': 'rospace_comm_detector',
    'module_version': '0.1.0',
    # Schema 的 producer.source 枚举只允许 MOCK / EXTERNAL / UNKNOWN。
    # 本模块是**真实外部模块**（非模拟），故取 EXTERNAL；
    # "由公开数据集离线训练、并非在线 DDS 监测" 这一限定写在
    # evidence_refs[].note 与 extensions.rospace_comm 中，
    # **不通过修改 Schema 来迁就数据集**。
    'source': 'EXTERNAL',
}
EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_MODEL_ERROR = 3
EXIT_MAPPING_BLOCKED = 4       # 字段语义不足，拒绝产出完整证据

RISK_BY_PREDICTION = {0: 'NONE', 1: 'HIGH'}
CATEGORY_BY_PREDICTION = {0: 'NONE', 1: 'NETWORK_TRAFFIC_ANOMALY'}


def read_stdin_json():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        print('ERROR: stdin 不是合法 JSON: {0}'.format(exc), file=sys.stderr)
        sys.exit(EXIT_INPUT_ERROR)
    if not isinstance(payload, dict):
        print('ERROR: 输入信封顶层必须是对象', file=sys.stderr)
        sys.exit(EXIT_INPUT_ERROR)
    return payload


def extract_features(envelope):
    """从信封中取出 ROSPaCe 特征向量。

    约定：`observations[].detail.rospace_comm.features` 为一个"特征名 -> 数值"对象。
    这是唯一被认可的来源；模块**不读取任何本地 CSV** 充当在线数据。
    """
    for observation in envelope.get('observations') or []:
        detail = observation.get('detail') or {}
        block = detail.get('rospace_comm') or {}
        features = block.get('features')
        if isinstance(features, dict) and features:
            return features, block
    return None, None


def extract_window_ms(envelope):
    """窗口长度只接受运行侧提供；否则按点观测取 0（不猜测）。"""
    for observation in envelope.get('observations') or []:
        detail = observation.get('detail') or {}
        block = detail.get('f0_runtime') or {}
        value = block.get('window_ms')
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)
    return 0.0


def extract_runtime_count(envelope):
    """只接受**运行侧**提供的业务请求计数。缺失则返回 None（不猜）。"""
    for observation in envelope.get('observations') or []:
        detail = observation.get('detail') or {}
        block = detail.get('f0_runtime') or {}
        value = block.get('request_count')
        if isinstance(value, int) and value >= 0:
            return value
    return None


def main() -> int:
    envelope = read_stdin_json()

    run_id = envelope.get('run_id') or ''
    request_id = envelope.get('request_id') or ''
    candidate = envelope.get('candidate_action') or {}
    resource = candidate.get('action_resource') or ''
    operation = (candidate.get('operation') or '').upper()
    created_at = envelope.get('created_at') or ''

    features, block = extract_features(envelope)
    if features is None:
        # 安全失败：不得用本地 CSV 或零值冒充在线特征
        print(json.dumps({
            'status': 'ERROR',
            'reason': 'ROSPACE_FEATURES_ABSENT',
            'detail': ('信封未提供 observations[].detail.rospace_comm.features。'
                       '本模块不会用本地 CSV、0 或训练集均值冒充在线特征。'),
        }, ensure_ascii=False), file=sys.stderr)
        return EXIT_INPUT_ERROR

    request_count = extract_runtime_count(envelope)
    window_ms = extract_window_ms(envelope)
    if request_count is None:
        print(json.dumps({
            'status': 'ERROR',
            'reason': 'MAPPING_BLOCKED_REQUEST_COUNT',
            'detail': ('信封未提供 observations[].detail.f0_runtime.request_count。'
                       'ROSPaCe 为逐包/逐窗口监测数据，无法真实产生"业务请求数"；'
                       '按约定不填 0、不用均值、不猜测，因此拒绝产出完整 '
                       'CommRiskEvidence。'),
        }, ensure_ascii=False), file=sys.stderr)
        return EXIT_MAPPING_BLOCKED

    # ---- 真实加载模型并推理 ----
    try:
        from predict import ModelBundle
    except ImportError as exc:
        print('ERROR: 无法导入推理模块: {0}'.format(exc), file=sys.stderr)
        return EXIT_MODEL_ERROR

    run_dir = block.get('model_run_dir') or os.path.join(
        os.path.dirname(os.path.dirname(MODULE_DIR)), 'training_runs', 'rospace_reduced')
    try:
        bundle = ModelBundle(run_dir)
    except SystemExit as exc:                 # 缺模型 / 缺 joblib
        print('ERROR: 模型加载失败: {0}'.format(exc), file=sys.stderr)
        return EXIT_MODEL_ERROR

    ok, detail, values = bundle.validate_row(dict(features))
    if not ok:
        print(json.dumps({'status': 'ERROR', 'reason': 'FEATURE_INCOMPATIBLE',
                          'detail': detail}, ensure_ascii=False), file=sys.stderr)
        return EXIT_INPUT_ERROR

    preds, probas = bundle.predict([values])
    prediction = int(preds[0])
    probability = round(float(probas[0]), 6) if probas is not None else None

    evidence = {
        'schema_version': SCHEMA_VERSION,
        'run_id': run_id,
        'request_id': request_id,
        'event_id': '{0}:rospace_comm'.format(request_id or 'unknown'),
        'producer': dict(PRODUCER),
        'observed_at': created_at,
        'status': 'SUSPICIOUS' if prediction == 1 else 'NORMAL',
        'reason': ('模型判定为通信流量异常' if prediction == 1
                   else '模型未在流量特征上发现异常'),
        # Schema 的 evidence_refs[].kind 枚举里没有"公开数据集离线推理"这一类。
        # 逐一排除：不是 RUNTIME_LOG（不是我们的运行日志）、
        # 不是 PERMISSION_FILE_ANALYSIS、不是 UNIT_TEST；
        # 也不能算 CONTROLLED_SECURITY_EXPERIMENT —— 那是**我们自己**做的受控实验，
        # 而这里是引用他人数据集的训练结果。因此如实取 UNKNOWN，
        # 并在 note 中写清实际含义，**不通过修改 Schema 来迁就数据**。
        'evidence_refs': [{
            'ref': 'rospace_comm:model',
            'kind': 'UNKNOWN',
            'note': ('来源为 ROSPaCe 公开数据集上离线训练的模型推理结果；'
                     '不属于 Schema 既有任一类别，故记 UNKNOWN。'
                     '该证据**不是** DDS 身份认证结果，**不是** F0 运行日志，'
                     '也**不是**我们执行的受控安全实验。'),
        }],
        'communication': {
            'resource': resource,
            # Schema 枚举为 ['Topic','Service','Action']
            'resource_type': 'Action' if operation else 'Topic',
        },
        'window': {
            'start': created_at,
            'end': created_at,
            # 单条记录推理等价于点观测，窗口长度 0 是如实值。
            # 若运行侧提供了真实窗口长度则优先采用。
            'duration_ms': window_ms,
        },
        # 由**运行侧**提供，非模型产生、非默认值
        'request_count': request_count,
        'anomaly_category': CATEGORY_BY_PREDICTION[prediction],
        'risk_level': RISK_BY_PREDICTION[prediction],
        'basis': [
            'ROSPaCe reduced 离线训练模型（SGDClassifier log_loss）',
            'model_sha256={0}'.format(bundle.model_sha256[:16]),
            'feature_config_sha256={0}'.format(bundle.config_sha256[:16]),
        ],
        'extensions': {
            'rospace_comm': {
                'model_run_dir': os.path.relpath(run_dir, os.path.dirname(os.path.dirname(MODULE_DIR))),
                'model_sha256': bundle.model_sha256,
                'attack_probability': probability,
                'prediction': prediction,
                'online_capability': 'NOT_READY',
                'online_capability_note': (
                    '本模型 61 个输入特征中 A 类（Jazzy 可直接获取）仅 4 个，'
                    '其余 57 个为 B/C 类，当前不具备在线采集链路。'
                    '详见 docs/data/ROSPaCe_JAZZY_FEATURE_FEASIBILITY.csv'),
                'request_count_provenance': 'provided_by_envelope_f0_runtime',
                'dataset_source': ('ROSPaCe Intrusion Detection Dataset for a ROS2-Based '
                                   'Cyber-Physical System (reduced)'),
            },
        },
    }
    sys.stdout.write(json.dumps(evidence, ensure_ascii=False) + '\n')
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
