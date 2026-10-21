"""Training-only preprocessing; validation selects algorithm/threshold; test is held out."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from modules.member1_comm.data import prepare
from modules.member1_comm.metrics import evaluate
from modules.member1_comm.module import FORBIDDEN, predict


def fit_preprocess(train):
    # Never called on validation/test. Explicitly report all-missing training columns.
    if np.any(np.isnan(train).all(axis=0)):
        raise ValueError('training feature all missing: change feature selection using training only')
    impute = np.nanmedian(train, axis=0)
    filled = np.where(np.isnan(train), impute, train)
    transformed = np.sign(filled) * np.log1p(np.abs(filled))
    scaler = StandardScaler().fit(transformed)
    return impute, scaler


def transform(x, impute, scaler):
    filled = np.where(np.isnan(x), impute, x)
    return scaler.transform(np.sign(filled) * np.log1p(np.abs(filled)))


def export_model(estimator, names, impute, scaler, threshold, gate):
    artifact = {'format':'member1-numeric-v1', 'feature_names':names, 'impute':impute.tolist(),
                'mean':scaler.mean_.tolist(), 'scale':scaler.scale_.tolist(), 'threshold':float(threshold),
                'validation_gate_passed':bool(gate), 'RUNTIME_MONITOR':'NOT_READY',
                'missing_policy':'explicit null -> train-only median; missing names/order rejected'}
    if isinstance(estimator, LogisticRegression):
        artifact.update(algorithm='logistic', weights=estimator.coef_[0].tolist(), intercept=float(estimator.intercept_[0]))
    else:
        trees = []
        for e in estimator.estimators_:
            tree = e.tree_
            values = tree.value[:,0,:]
            probabilities = values[:,1] / values.sum(axis=1)
            trees.append({'left':tree.children_left.tolist(), 'right':tree.children_right.tolist(),
                          'feature':tree.feature.tolist(), 'threshold':tree.threshold.tolist(), 'probability':probabilities.tolist()})
        artifact.update(algorithm='extra_trees', trees=trees)
    return artifact


def run(samples, output, validation_shards=2, test_shards=2):
    samples, output = Path(samples), Path(output)
    manifest = json.loads((samples/'manifest.json').read_text(encoding='utf-8'))
    names = manifest['feature_names']
    if any(n.lower() in FORBIDDEN for n in names):
        raise ValueError('label/time/group leakage into features')
    files = sorted(manifest['files'], key=lambda f:f['shard'])
    if len(files) <= validation_shards + test_shards or min(validation_shards,test_shards) < 1:
        raise ValueError('need disjoint nonempty train/validation/test shards')
    split = {'train':files[:-(validation_shards+test_shards)],
             'validation':files[-(validation_shards+test_shards):-test_shards], 'test':files[-test_shards:]}
    data = {}
    for part, selected in split.items():
        x, labels = [], []
        for file in selected:
            with np.load(samples/file['sample_file'], allow_pickle=False) as archive:
                x.append(archive['x'])
                labels.extend(archive['labels'].tolist())
        data[part] = (np.concatenate(x), labels)
        if len(set(int(label != 'observe') for label in labels)) != 2:
            raise ValueError(part + ' must contain normal and attacks; no meaningful binary evaluation')
    impute, scaler = fit_preprocess(data['train'][0])
    transformed = {part:transform(value[0], impute, scaler) for part,value in data.items()}
    ytrain = np.array([int(label!='observe') for label in data['train'][1]])
    candidates = [LogisticRegression(class_weight='balanced', max_iter=1000, C=0.1, random_state=42),
                  ExtraTreesClassifier(n_estimators=48, max_depth=12, min_samples_leaf=10, class_weight='balanced', n_jobs=2, random_state=42)]
    comparisons = []
    best = None
    for estimator in candidates:
        estimator.fit(transformed['train'], ytrain)
        probabilities = estimator.predict_proba(transformed['validation'])[:,1]
        # Fixed grid uses validation only; test is evaluated once AFTER selection.
        choices = []
        for threshold in [0.1,0.25,0.5,0.75,0.9]:
            metrics = evaluate(data['validation'][1], (probabilities>=threshold).astype(int).tolist(), probabilities)
            choices.append((metrics['balanced_accuracy'], metrics['f1'], threshold, metrics))
        _, _, threshold, metrics = max(choices, key=lambda row:(row[0],row[1],-abs(row[2]-0.5)))
        comparisons.append({'algorithm':type(estimator).__name__, 'threshold':threshold, 'validation':metrics})
        if best is None or (metrics['balanced_accuracy'], metrics['f1']) > (best[2]['balanced_accuracy'],best[2]['f1']):
            best = estimator, threshold, metrics
    estimator, threshold, validation = best
    attack_baseline = evaluate(data['validation'][1], [1]*len(data['validation'][1]))
    gate = (validation['f1'] > attack_baseline['f1'] and validation['balanced_accuracy'] > 0.5
            and validation['recall'] >= 0.5 and validation['specificity'] >= 0.5)
    output.mkdir(parents=True, exist_ok=True)
    artifact = export_model(estimator,names,impute,scaler,threshold,gate)
    encoded = json.dumps(artifact,allow_nan=False,separators=(',',':')).encode()
    (output/'model.json').write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    (output/'model.sha256').write_text(digest+'\n',encoding='utf-8')
    probabilities = estimator.predict_proba(transformed['test'])[:,1]
    labels = data['test'][1]
    # Real held-out data must also agree with the dependency-free deployed
    # numeric implementation, not just with the sklearn training object.
    numeric_scores = np.asarray([predict(artifact,{'feature_names':names,
        'values':[None if np.isnan(value) else float(value) for value in row]})
        for row in data['test'][0]])
    parity_error = float(np.max(np.abs(numeric_scores-probabilities)))
    parity_mismatches = int(np.sum((numeric_scores>=threshold)!=(probabilities>=threshold)))
    if parity_error > 1e-6 or parity_mismatches:
        raise ValueError('deployed numeric inference disagrees with held-out sklearn predictions')
    result = evaluate(labels,(probabilities>=threshold).astype(int).tolist(),probabilities)
    # Diagnosis: sampled shard mean/std/missing rates and capture-time ranges, not causal claims.
    diagnostics = []
    for part, selected in split.items():
        for file in selected:
            with np.load(samples/file['sample_file'],allow_pickle=False) as a:
                finite = np.where(np.isnan(a['x']), impute, a['x'])
                shifted = np.sign(finite)*np.log1p(np.abs(finite))
                times = a['timestamps'].tolist()
                labels_by_row = a['labels'].tolist()
                label_times = {}
                for label in sorted(set(labels_by_row)):
                    values = [stamp for stamp,item in zip(times,labels_by_row) if item==label]
                    label_times[label] = {'sample_count':len(values),'min_lexical':min(values),'max_lexical':max(values)}
                diagnostics.append({'split':part, 'shard':file['shard'], 'sample_mean_signed_log':shifted.mean(axis=0).tolist(),
                    'sample_std_signed_log':shifted.std(axis=0).tolist(), 'missing_fraction':file['missing_fraction'],
                    'timestamp_min_lexical':min(times), 'timestamp_max_lexical':max(times), 'class_counts':file['sample_labels'],
                    'sample_label_timestamp_ranges_lexical':label_times,
                    'time_range_scope':'sampled lexical ranges only; no capture-session or causal claim'})
    report = {'baseline_sha':'a4c597161d254192b662ee7b8f4d17f76a89cc16', 'contract_status':'PROPOSED_V1',
        'data_manifest':manifest, 'split':{p:[f['shard'] for f in fs] for p,fs in split.items()},
        'split_type':'FILE_DISJOINT_SPLIT', 'SESSION_INDEPENDENCE':'UNVERIFIED', 'feature_count':len(names),
        'preprocessing_fit':'train only; immutable before validation/test', 'validation_comparisons':comparisons,
        'selected_algorithm':artifact['algorithm'], 'selected_threshold':threshold,'model_sha256':digest,
        'validation_gate_passed':gate, 'test':result,
        'deployed_numeric_parity':{'status':'PASS','test_rows':len(labels),
            'max_probability_error':parity_error,'classification_mismatches':parity_mismatches},
        'test_always_attack':evaluate(labels,[1]*len(labels)), 'test_always_normal':evaluate(labels,[0]*len(labels)),
        'diagnostics':diagnostics, 'RUNTIME_MONITOR':'NOT_READY',
        'detector_effectiveness':'PARTIAL_OFFLINE_FILE_SPLIT' if gate else 'NOT_PROVEN',
        'prior_model_reproduction':'BLOCKED: prior trained artifact unavailable; do not equate new comparison with reproduction'}
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'output':str(output),'algorithm':artifact['algorithm'],'gate':gate,'test':result},indent=2),flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--features',type=Path,default=ROOT/'modules/member1_comm/features.json')
    parser.add_argument('--samples',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--rows-per-shard',type=int,default=10000)
    args = parser.parse_args()
    if args.archive:
        names=json.loads(args.features.read_text(encoding='utf-8'))['feature_names']
        prepare(args.archive,args.samples,names,args.rows_per_shard)
    run(args.samples,args.output)


if __name__ == '__main__':
    main()
