"""成员一通信风险模块（适配后）：纯数值 JSON 模型 -> CommRiskEvidence。

本文件是 `user/RosSystem-member1-delivery/.../modules/my_comm/module.py`
（成员一交付，源文件 SHA-256 见 docs/integration/member_module_handoff.yaml）
在主系统中的**适配版本**。算法、训练流程与失败关闭设计未改写；改动集中在
安全语义与工程适配上：

适配点（逐条对应 WORK_A 报告）
==============================
1. 模块目录由 `modules/my_comm` 迁移到 `modules/member1_comm`（与仓库既有
   `modules/member3_taskrisk` 命名一致），只改包路径，不改算法。
2. 模型根目录从"只允许 training_runs/"改为**受信任白名单**：
   `training_runs/`（本地训练）与 `modules/member1_comm/model/`（随仓库交付、
   可复验的模型）。仍然拒绝任意路径，也拒绝从输入信封指定模型。
3. 新增 `--features` 特征清单校验：模型内嵌的 feature_names 必须与
   `features.json` 完全一致，否则失败关闭为 ERROR，避免"模型与特征清单漂移"。
4. **观察来源可信性必须来自受信任配置**。原实现直接相信信封里的
   `observations[].kind`（业务输入自报）；若模型通过验证门槛，一条自报
   `kind=RUNTIME_LOG` 的输入就能换来 NORMAL。现在 NORMAL 需要同时满足：
   模型验证门槛通过 + 受信任配置 `--observation-provenance` 声明了可信来源 +
   信封自报 kind 与该来源一致。三者缺一即 UNKNOWN。
5. `extensions.my_comm` 更名为 `extensions.member1_comm`，并记录
   `trusted_provenance` / `envelope_provenance` 供追溯。

安全边界（未改变，且不得被下游放宽）
===================================
* 本模块输出只是**研究建议**。SUSPICIOUS/UNKNOWN 都不得推进；NORMAL 也不代表
  Gateway 允许，更不代表 DDS 身份可信。
* `validation_gate_passed=false` 的模型不得给出 NORMAL；`--controlled-test`
  只在受控 L1 测试配置中使用，该 flag 只能来自受信任命令行。
* 缺模型退出 3；非法信封退出 2；无法形成映射退出 4。绝不伪造完整证据。
* 不加载 pickle/joblib；模型必须是纯数值 JSON + SHA-256 校验。
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import validate_team_contracts as contracts

VERSION = '0.3.0'
MAX_INPUT = 1048576
MAX_MODEL = 33554432
FORBIDDEN = {'attack', 'label', 'target', 'timestamp', 'session_id', 'group_id'}
#: 允许存放模型的仓库目录（受信任白名单，路径仍须落在仓库内）。
MODEL_ROOTS = ('training_runs', 'modules/member1_comm/model')
#: 只有这两类观察来源才可能支撑"正常"结论；且必须由受信任配置声明。
TRUSTED_PROVENANCE = ('RUNTIME_LOG', 'CONTROLLED_SECURITY_EXPERIMENT')
PROVENANCE_CHOICES = ('UNKNOWN',) + TRUSTED_PROVENANCE + ('MOCK',)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('nonfinite JSON value: ' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def validate(document, name):
    from jsonschema import Draft202012Validator
    schema = strict_json((ROOT / 'docs/interfaces/schemas' / (name + '.schema.json')).read_bytes())
    Draft202012Validator(schema, format_checker=contracts.build_format_checker()).validate(document)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('expected finite numeric value')
    return float(value)


def dt(value):
    if not contracts.check_rfc3339(value):
        raise ValueError('invalid RFC3339 time')
    return datetime.fromisoformat(value.upper().replace('Z', '+00:00'))


def load_feature_manifest(path):
    """读取特征清单（受信任本地文件），只取 feature_names。"""
    document = strict_json(Path(path).read_bytes())
    names = document.get('feature_names')
    if not isinstance(names, list) or not names:
        raise ValueError('FEATURE_MANIFEST_INVALID: feature_names missing')
    return names


def load_model(path, expected_hash, features_path=None):
    path = Path(path).resolve()
    allowed = [(ROOT / root).resolve() for root in MODEL_ROOTS]
    if not any(path.is_relative_to(root) for root in allowed):
        raise ValueError('model must live under one of ' + ', '.join(MODEL_ROOTS))
    if path.stat().st_size > MAX_MODEL:
        raise ValueError('model too large')
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if not expected_hash or digest != expected_hash:
        raise ValueError('model SHA256 missing or mismatched')
    model = strict_json(raw)
    names = model['feature_names']
    if not isinstance(names, list) or not 1 <= len(names) <= 128 or any(not isinstance(n, str) for n in names) or len(set(names)) != len(names):
        raise ValueError('invalid feature names')
    if any(not n or n.lower() in FORBIDDEN for n in names):
        raise ValueError('label/time/group leakage into model')
    if features_path is not None:
        declared = load_feature_manifest(features_path)
        if declared != names:
            raise ValueError('MODEL_FEATURE_LIST_MISMATCH: model features differ from features.json')
    n = len(names)
    if model['format'] != 'member1-numeric-v1' or model['algorithm'] not in {'logistic', 'extra_trees'}:
        raise ValueError('unknown model format/algorithm')
    for key in ('mean', 'scale', 'impute'):
        if len(model[key]) != n:
            raise ValueError('preprocessing shape mismatch')
        for item in model[key]:
            number(item)
    if any(s <= 0 for s in model['scale']):
        raise ValueError('invalid preprocessing scales')
    threshold = number(model['threshold'])
    if not 0 < threshold < 1:
        raise ValueError('invalid threshold')
    if type(model['validation_gate_passed']) is not bool:
        raise ValueError('validation gate missing')
    if model['algorithm'] == 'logistic':
        if len(model['weights']) != n:
            raise ValueError('weight shape mismatch')
        for w in model['weights']:
            number(w)
        number(model['intercept'])
    else:
        trees = model['trees']
        if not isinstance(trees, list) or not 1 <= len(trees) <= 256:
            raise ValueError('invalid trees')
        for tree in trees:
            size = len(tree['left'])
            if not 1 <= size <= 100000 or any(len(tree[k]) != size for k in ('right', 'feature', 'threshold', 'probability')):
                raise ValueError('invalid tree shape')
            for i, (left, right, feature, cut, probability) in enumerate(zip(tree['left'], tree['right'], tree['feature'], tree['threshold'], tree['probability'])):
                if not 0 <= number(probability) <= 1:
                    raise ValueError('invalid leaf probability')
                number(cut)
                if left == right == -1:
                    continue
                if type(left) is not int or type(right) is not int or not i < left < size or not i < right < size:
                    raise ValueError('invalid tree child index')
                if type(feature) is not int or not 0 <= feature < n:
                    raise ValueError('invalid tree feature index')
    return model, digest


def predict(model, features):
    if not isinstance(features, dict) or features.get('feature_names') != model['feature_names']:
        raise ValueError('FEATURE_NAMES_ABSENT_OR_ORDER_MISMATCH')
    values = features.get('values')
    if not isinstance(values, list) or len(values) != len(model['feature_names']):
        raise ValueError('FEATURE_VALUES_ABSENT_OR_SHAPE_MISMATCH')
    if any(key.lower() in FORBIDDEN for key in features):
        raise ValueError('LABEL_LEAKAGE_IN_FEATURES')
    # A present null is explicit dataset missingness, distinct from absent features.
    # The train-only median and missingness count are declared in model/output.
    raw = [model['impute'][i] if value is None else number(value) for i, value in enumerate(values)]
    x = [(math.copysign(math.log1p(abs(v)), v) - mu) / sigma for v, mu, sigma in zip(raw, model['mean'], model['scale'])]
    if model['algorithm'] == 'logistic':
        z = sum(v * w for v, w in zip(x, model['weights'])) + model['intercept']
        return 1 / (1 + math.exp(-max(-700, min(700, z))))
    probabilities = []
    for tree in model['trees']:
        node = 0
        while tree['left'][node] != -1:
            node = tree['left'][node] if x[tree['feature'][node]] <= tree['threshold'][node] else tree['right'][node]
        probabilities.append(tree['probability'][node])
    return sum(probabilities) / len(probabilities)


def observation(envelope):
    usable = [obs for obs in envelope['observations'] if any(k in obs.get('detail', {}) for k in ('rospace_comm', 'f0_runtime'))]
    if len(usable) != 1:
        raise ValueError('exactly one correlated communication observation is required')
    obs = usable[0]
    runtime = obs.get('detail', {}).get('f0_runtime', {})
    for key in ('request_count', 'communication', 'window'):
        if key not in runtime:
            raise ValueError('MAPPING_BLOCKED: missing f0_runtime.' + key)
    count = runtime['request_count']
    if type(count) is not int or not 0 <= count <= 100000000:
        raise ValueError('invalid request_count')
    if runtime['communication'].get('resource') != obs['source']:
        raise ValueError('communication resource and observation source mismatch')
    window = runtime['window']
    duration = (dt(window['end']) - dt(window['start'])).total_seconds() * 1000
    if duration <= 0 or abs(duration - number(window['duration_ms'])) > 1:
        raise ValueError('window duration missing, reversed or inconsistent')
    if not dt(window['start']) <= dt(obs['observed_at']) <= dt(window['end']):
        raise ValueError('observation outside declared window')
    refs = [ref for ref in envelope['evidence_refs'] if ref['kind'] == obs['kind']]
    if not refs:
        raise ValueError('missing matching evidence provenance')
    return obs, runtime, refs


def normal_allowed(provenance, observed_kind, gate_passed):
    """NORMAL 的三个必要条件：模型门槛 + 受信任来源 + 信封声明一致。

    任何一个条件单独成立都不够。尤其是 observed_kind：它来自业务输入，
    本身**不可信**；它的作用只是"与受信任配置声明比对"，比对失败即视为
    伪造或错配，直接保留 UNKNOWN。
    """
    if not gate_passed:
        return (False, 'MODEL_NOT_ACCEPTED_OR_UNTRUSTED_OBSERVATION: normal prediction withheld',
                'MODEL_NOT_ACCEPTED')
    if provenance not in TRUSTED_PROVENANCE:
        return (False,
                ('OBSERVATION_PROVENANCE_NOT_TRUSTED: trusted config declares {0!r}; '
                 'business JSON cannot establish the observation source').format(provenance),
                'OBSERVATION_PROVENANCE_NOT_TRUSTED')
    if observed_kind != provenance:
        return (False,
                ('OBSERVATION_PROVENANCE_MISMATCH: envelope claims {0!r}, '
                 'trusted config declares {1!r}').format(observed_kind, provenance),
                'OBSERVATION_PROVENANCE_MISMATCH')
    return True, '', 'BELOW_THRESHOLD_VALIDATED'


def analyse(module, envelope, context):
    """Actual model decision. f0_mock, business labels and desired states are ignored."""
    if module != 'comm_risk':
        raise ValueError('module identity must be comm_risk')
    obs, runtime, refs = observation(envelope)
    provenance = context.get('observation_provenance') or 'UNKNOWN'
    if provenance not in PROVENANCE_CHOICES:
        raise ValueError('invalid observation provenance')
    age = (dt(envelope['created_at']) - dt(obs['observed_at'])).total_seconds()
    state, score, category, risk = 'UNKNOWN', None, 'UNKNOWN', 'UNKNOWN'
    reason = 'FEATURES_ABSENT: offline communication feature vector unavailable'
    #: 机器可读的原因码，写入 extensions.member1_comm.reason_code。
    #: 它只是 reason 的稳定前缀，不改变任何状态语义。
    reason_code = 'FEATURES_ABSENT'
    digest = None
    if age < 0 or age > 300:
        reason = 'OBSERVATION_STALE_OR_FUTURE: relative to envelope created_at'
        reason_code = 'OBSERVATION_STALE_OR_FUTURE'
    else:
        try:
            model, digest = load_model(context['model'], context['model_sha256'],
                                       context.get('features'))
        except FileNotFoundError:
            raise FileNotFoundError('MODEL_ABSENT: no usable numeric model') from None
        except (KeyError, TypeError, ValueError) as exc:
            state, reason = 'ERROR', 'MODEL_INVALID: ' + str(exc)
            reason_code = 'MODEL_INVALID'
        else:
            try:
                block = obs.get('detail', {}).get('rospace_comm', {})
                score = predict(model, block.get('features'))
            except (KeyError, TypeError, ValueError) as exc:
                reason = 'FEATURES_INVALID: ' + str(exc)
                reason_code = 'FEATURES_INVALID'
            else:
                attack = score >= model['threshold']
                if attack:
                    state, category, risk = 'SUSPICIOUS', 'UNKNOWN', 'MEDIUM'
                    reason = 'Offline model detects anomaly; binary output cannot identify an attack subtype'
                    reason_code = 'ANOMALY_DETECTED'
                else:
                    allowed, why, code = normal_allowed(
                        provenance, obs['kind'], model['validation_gate_passed'])
                    if allowed:
                        state, category, risk = 'NORMAL', 'NONE', 'NONE'
                        reason = 'Offline classifier below threshold within its validation scope; advisory only'
                        reason_code = code
                    elif context.get('controlled_test'):
                        state, category, risk = 'NORMAL', 'NONE', 'NONE'
                        reason = ('CONTROLLED_TEST_ONLY: classifier below threshold; '
                                  'no production effectiveness claim. ' + why)
                        reason_code = 'CONTROLLED_TEST_BELOW_THRESHOLD'
                    else:
                        reason = why
                        reason_code = code
    detail = {'reason': reason, 'communication': runtime['communication'], 'window': runtime['window'],
              'request_count': runtime['request_count'], 'anomaly_category': category, 'risk_level': risk,
              'basis': ['Offline classification only; RUNTIME_MONITOR: NOT_READY',
                        'trusted_observation_provenance=' + provenance,
                        'envelope_observation_kind=' + str(obs.get('kind'))[:64], reason[:256]],
              'evidence_refs': refs,
              'extensions': {'member1_comm': {'algorithm': 'numeric-model', 'score': score,
                  'model_sha256': digest, 'controlled_test': bool(context.get('controlled_test')),
                  'RUNTIME_MONITOR': 'NOT_READY', 'request_id_is_identity': False,
                  'trusted_provenance': provenance,
                  'envelope_provenance': obs.get('kind'),
                  'reason_code': reason_code,
                  'feature_manifest_verified': bool(context.get('features')) and digest is not None}}}
    if digest:
        detail['basis'].append('model_sha256=' + digest)
    values = obs.get('detail', {}).get('rospace_comm', {}).get('features', {})
    if isinstance(values, dict) and isinstance(values.get('values'), list):
        missing = sum(value is None for value in values['values'])
        detail['extensions']['member1_comm']['explicit_missing_value_count'] = missing
        if missing:
            detail['basis'].append(f'{missing} explicit null values: train-only median imputation; absent feature names are rejected')
    frequency = runtime['request_count'] * 1000 / runtime['window']['duration_ms']
    if frequency <= 1000000:
        detail['frequency_hz'] = frequency
    return state, detail


def build_output(envelope, state, detail):
    return {'schema_version': '1.0.0-proposed', 'run_id': envelope['run_id'], 'request_id': envelope['request_id'],
            'event_id': 'comm-' + uuid.uuid4().hex, 'producer': {'name': 'member1_rospace_comm', 'source': 'EXTERNAL', 'module_version': VERSION},
            'observed_at': datetime.now(timezone.utc).isoformat(), 'status': state, **detail}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', choices=['comm_risk'], default='comm_risk')
    parser.add_argument('--model', default=str(ROOT / 'modules/member1_comm/model/comm_risk_model.json'))
    parser.add_argument('--model-sha256', required=True)
    parser.add_argument('--features', default=str(HERE / 'features.json'),
                        help='特征清单（受信任本地文件），必须与模型内嵌 feature_names 一致')
    parser.add_argument('--observation-provenance', choices=PROVENANCE_CHOICES, default='UNKNOWN',
                        help='受信任配置声明的观察来源；业务 JSON 不得提供')
    parser.add_argument('--controlled-test', action='store_true', help='Trusted test config only; permits normal predictions from unvalidated models')
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('input exceeds limit')
        envelope = strict_json(raw)
        validate(envelope, 'module_input')
    except Exception as exc:
        print('INPUT_INVALID: ' + type(exc).__name__, file=sys.stderr)
        return 2
    try:
        state, detail = analyse(args.module, envelope, vars(args))
        output = build_output(envelope, state, detail)
        validate(output, 'comm_risk_evidence')
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print('MAPPING_OR_INTERNAL_ERROR: ' + str(exc)[:256], file=sys.stderr)
        return 4
    print(json.dumps(output, ensure_ascii=False, allow_nan=False))
    print('status=' + state + '; offline advisory only', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
