"""Member-one offline numeric model -> proposed CommRiskEvidence."""
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

VERSION = '0.2.0'
MAX_INPUT = 1048576
MAX_MODEL = 33554432
FORBIDDEN = {'attack', 'label', 'target', 'timestamp', 'session_id', 'group_id'}


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


def load_model(path, expected_hash):
    path = Path(path).resolve()
    if not path.is_relative_to((ROOT / 'training_runs').resolve()):
        raise ValueError('model must be inside repository training_runs')
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


def analyse(module, envelope, context):
    """Actual model decision. f0_mock, business labels and desired states are ignored."""
    if module != 'comm_risk':
        raise ValueError('module identity must be comm_risk')
    obs, runtime, refs = observation(envelope)
    age = (dt(envelope['created_at']) - dt(obs['observed_at'])).total_seconds()
    state, score, category, risk = 'UNKNOWN', None, 'UNKNOWN', 'UNKNOWN'
    reason = 'FEATURES_ABSENT: offline communication feature vector unavailable'
    digest = None
    if age < 0 or age > 300:
        reason = 'OBSERVATION_STALE_OR_FUTURE: relative to envelope created_at'
    else:
        try:
            model, digest = load_model(context['model'], context['model_sha256'])
        except FileNotFoundError:
            raise FileNotFoundError('MODEL_ABSENT: no usable numeric model') from None
        except (KeyError, TypeError, ValueError) as exc:
            state, reason = 'ERROR', 'MODEL_INVALID: ' + str(exc)
        else:
            try:
                block = obs.get('detail', {}).get('rospace_comm', {})
                score = predict(model, block.get('features'))
            except (KeyError, TypeError, ValueError) as exc:
                reason = 'FEATURES_INVALID: ' + str(exc)
            else:
                attack = score >= model['threshold']
                if attack:
                    state, category, risk = 'SUSPICIOUS', 'UNKNOWN', 'MEDIUM'
                    reason = 'Offline model detects anomaly; binary output cannot identify an attack subtype'
                elif model['validation_gate_passed'] and obs['kind'] in {'RUNTIME_LOG', 'CONTROLLED_SECURITY_EXPERIMENT'}:
                    state, category, risk = 'NORMAL', 'NONE', 'NONE'
                    reason = 'Offline classifier below threshold within its validation scope; advisory only'
                elif context.get('controlled_test'):
                    state, category, risk = 'NORMAL', 'NONE', 'NONE'
                    reason = 'CONTROLLED_TEST_ONLY: classifier below threshold; no production effectiveness claim'
                else:
                    reason = 'MODEL_NOT_ACCEPTED_OR_UNTRUSTED_OBSERVATION: normal prediction withheld'
    detail = {'reason': reason, 'communication': runtime['communication'], 'window': runtime['window'],
              'request_count': runtime['request_count'], 'anomaly_category': category, 'risk_level': risk,
              'basis': ['Offline classification only; RUNTIME_MONITOR: NOT_READY', reason[:256]], 'evidence_refs': refs,
              'extensions': {'my_comm': {'algorithm': 'numeric-model', 'score': score, 'model_sha256': digest,
                  'controlled_test': bool(context.get('controlled_test')), 'RUNTIME_MONITOR': 'NOT_READY', 'request_id_is_identity': False}}}
    if digest:
        detail['basis'].append('model_sha256=' + digest)
    values = obs.get('detail', {}).get('rospace_comm', {}).get('features', {})
    if isinstance(values, dict) and isinstance(values.get('values'), list):
        missing = sum(value is None for value in values['values'])
        detail['extensions']['my_comm']['explicit_missing_value_count'] = missing
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
    parser.add_argument('--model', default=str(ROOT / 'training_runs/member1/model.json'))
    parser.add_argument('--model-sha256', required=True)
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
