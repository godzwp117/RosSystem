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

#: Schema 允许的 anomaly_category 枚举（不得新增取值）。
#:   ['NONE','REQUEST_RATE_ANOMALY','DUPLICATE_CALL_PATTERN','TIMING_DEVIATION',
#:    'UNEXPECTED_RESOURCE_ACCESS','NODE_RELATION_ANOMALY','UNKNOWN']
#:
#: 本模型是**二分类**（observe vs 其余 6 类合并），无法把预测对应到
#: 上述任一具体类别。因此攻击预测一律记 `UNKNOWN` ——
#: 含义是"**检出异常但无法精确归类**"，**不是**"通信正常"。
CATEGORY_BY_PREDICTION = {0: 'NONE', 1: 'UNKNOWN'}

#: 风险等级按**预测置信度**分档，而不是把所有攻击一律宣称为 HIGH。
#: 依据：SGDClassifier(log_loss) 提供 predict_proba；阈值为固定规则，
#: 记录在 basis 中。缺少概率时记 UNKNOWN，不猜测。
RISK_THRESHOLDS = ((0.95, 'HIGH'), (0.80, 'MEDIUM'), (0.50, 'LOW'))


def risk_from_probability(prediction: int, probability):
    """把 (预测, 概率) 映射为 Schema 允许的 risk_level。

    返回 (risk_level, 依据文本)。概率不可得时返回 UNKNOWN。
    """
    if prediction == 0:
        return 'NONE', '模型判定为正常'
    if probability is None:
        return 'UNKNOWN', '模型判定为异常，但未提供置信度，无法分档'
    for threshold, level in RISK_THRESHOLDS:
        if probability >= threshold:
            return level, '模型判定为异常且 attack_probability={0:.4f} >= {1}'.format(
                probability, threshold)
    return 'LOW', '模型判定为异常但置信度低于最小阈值 0.50'


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


def resolve_model_dir(cli_value):
    """确定并校验模型目录。返回 (绝对路径 或 None, 说明)。

    可信来源只有命令行参数（由受信任配置文件的 command 数组提供）。
    额外做两道约束：
      * 目录必须位于本仓库的 training_runs/ 之下 —— 拒绝任意绝对路径；
      * 目录必须真实存在且含完整产物。
    """
    repo_root = os.path.dirname(os.path.dirname(MODULE_DIR))
    trusted_root = os.path.join(repo_root, 'training_runs')
    candidate = cli_value or os.path.join(trusted_root, 'rospace_reduced')
    if not os.path.isabs(candidate):
        candidate = os.path.join(repo_root, candidate)
    real = os.path.realpath(candidate)
    if not _is_within(real, trusted_root):
        return None, ('模型目录 {0} 不在受信任根 {1} 之下，拒绝加载。'
                      '业务输入无法切换模型。').format(real, trusted_root)
    if not os.path.isdir(real):
        return None, '模型目录不存在: {0}'.format(real)
    missing = [n for n in ('feature_config.json', 'model.joblib', 'scaler.joblib')
               if not os.path.isfile(os.path.join(real, n))]
    if missing:
        return None, '模型目录缺少产物 {0}'.format(missing)
    return real, 'trusted-root={0}'.format(trusted_root)


def _is_within(path, parent):
    try:
        left, right = os.path.realpath(path), os.path.realpath(parent)
    except (OSError, ValueError):
        return False
    try:
        return os.path.commonpath([left, right]) == right
    except ValueError:
        return False


def main() -> int:
    global args
    import argparse
    parser = argparse.ArgumentParser(description='ROSPaCe 检测模型 F0 外部模块')
    parser.add_argument('--model-run-dir', default=None,
                        help='模型目录（只能由受信任配置的 command 数组传入）')
    args = parser.parse_args()
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
        from predict import ModelArtifactError, ModelBundle
    except ImportError as exc:
        print('ERROR: 无法导入推理模块: {0}'.format(exc), file=sys.stderr)
        return EXIT_MODEL_ERROR

    # **模型目录只来自受信任的命令行参数**（由受信任的本地配置文件经
    # command 参数数组传入），绝不从业务输入读取。
    # joblib 是可反序列化执行内容，允许业务数据指定路径等于给出远程代码执行面。
    run_dir, provenance = resolve_model_dir(args.model_run_dir)
    if run_dir is None:
        print(json.dumps({'status': 'ERROR', 'reason': 'MODEL_DIR_UNTRUSTED',
                          'detail': provenance}, ensure_ascii=False), file=sys.stderr)
        return EXIT_MODEL_ERROR
    if block.get('model_run_dir'):
        # 记录"输入试图切换模型"这一事实，但**不采纳**
        print('[warn] 信封提供了 model_run_dir={0!r}，已忽略；'
              '模型目录只能来自受信任的命令行参数。'.format(block['model_run_dir']),
              file=sys.stderr)
    try:
        bundle = ModelBundle(run_dir)
    except ModelArtifactError as exc:         # 损坏 / 格式不符 / 版本不兼容
        print(json.dumps({'status': 'ERROR', 'reason': 'MODEL_ARTIFACT_INVALID',
                          'detail': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_MODEL_ERROR
    except SystemExit as exc:                 # 缺模型 / 缺 joblib
        print('ERROR: 模型加载失败: {0}'.format(exc), file=sys.stderr)
        return EXIT_MODEL_ERROR
    except Exception as exc:                  # noqa: BLE001
        # 兜底：任何其它加载期异常都不得被解释为正常通信
        print(json.dumps({'status': 'ERROR', 'reason': 'MODEL_LOAD_FAILED',
                          'detail': '{0}: {1}'.format(type(exc).__name__, exc)},
                         ensure_ascii=False), file=sys.stderr)
        return EXIT_MODEL_ERROR

    ok, detail, values = bundle.validate_row(dict(features))
    if not ok:
        print(json.dumps({'status': 'ERROR', 'reason': 'FEATURE_INCOMPATIBLE',
                          'detail': detail}, ensure_ascii=False), file=sys.stderr)
        return EXIT_INPUT_ERROR

    preds, probas = bundle.predict([values])
    prediction = int(preds[0])
    probability = round(float(probas[0]), 6) if probas is not None else None
    risk_level, risk_basis = risk_from_probability(prediction, probability)

    evidence = {
        'schema_version': SCHEMA_VERSION,
        'run_id': run_id,
        'request_id': request_id,
        'event_id': '{0}:rospace_comm'.format(request_id or 'unknown'),
        'producer': dict(PRODUCER),
        'observed_at': created_at,
        'status': 'SUSPICIOUS' if prediction == 1 else 'NORMAL',
        'reason': ('离线模型在通信流量特征上检出异常；'
                   '二分类无法对应到具体异常类别，故 anomaly_category=UNKNOWN'
                   '（表示无法精确归类，不表示通信正常）' if prediction == 1
                   else '离线模型未在流量特征上发现异常'),
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
        'risk_level': risk_level,
        'basis': [
            'ROSPaCe reduced 离线训练模型（SGDClassifier log_loss）',
            'model_sha256={0}'.format(bundle.model_sha256[:16]),
            'feature_config_sha256={0}'.format(bundle.config_sha256[:16]),
            'risk_level 依据: {0}'.format(risk_basis),
            '模型目录来源: {0}（业务输入不可指定）'.format(provenance),
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
                'risk_level_basis': risk_basis,
                'model_dir_provenance': provenance,
                'request_count_provenance': 'provided_by_envelope_f0_runtime',
                'anomaly_category_note': ('二分类模型无法对应到具体异常类别，'
                                          'UNKNOWN 表示无法精确归类，不表示正常'),
                'dataset_source': ('ROSPaCe Intrusion Detection Dataset for a ROS2-Based '
                                   'Cyber-Physical System (reduced)'),
            },
        },
    }
    sys.stdout.write(json.dumps(evidence, ensure_ascii=False) + '\n')
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
