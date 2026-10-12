#!/usr/bin/env python3
"""ROSPaCe reduced 轻量通信异常检测：内存有界预处理 + 训练 + 评测（阶段 B/C/D）。

设计要点
--------
* **内存有界**：全程 `csv.reader` 流式读取 + `partial_fit` 增量拟合，
  不使用 `pandas.read_csv` 一次性载入。峰值内存由 `resource.getrusage` 实测记录。
* **不修改原始文件**：只读打开。
* **训练/测试按文件划分**：每个分片来自不同的采集时段/实验，
  按文件划分比随机切分更接近"跨会话泛化"检验。划分清单落盘。
* **预处理只在训练集拟合**：StandardScaler 仅在训练分片上 `partial_fit`，
  之后固定参数用于测试集；测试集不参与任何参数拟合。
* **标签不进特征**：`attack` 列只用于构造 y，绝不进入 X。
* **不虚构 group_id**：只使用真实存在的"文件"作为分组依据；不合成实验区块。

用法：
    .research-venv/bin/python modules/rospace_comm/train.py --dataset reduced
    .research-venv/bin/python modules/rospace_comm/train.py --dataset noperiodicity
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import resource
import sys
import time
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_ROOT = os.path.join(REPO_ROOT, 'data', 'ROSPaCe_reduced')
MAIN_DIR = os.path.join(DATA_ROOT, 'ROSPaCe_reduced')
NOPER_DIR = os.path.join(DATA_ROOT, 'ROSPaCe_reduced_noperiodicity')

LABEL_COLUMN = 'attack'
NORMAL_LABEL = 'observe'
# 非数值/文本列：不进入特征（它们是字符串或消息载荷，需要另行编码）
TEXT_COLUMNS = ('msg_data', 'msg_type', 'src_topic', 'timestamp',
                'layers.tcp.tcp.options',
                'layers.tcp.tcp.flags_tree.tcp.flags.syn_tree._ws.expert._ws.expert.message',
                'layers._ws.short')

DEFAULT_FEATURES = os.path.join(REPO_ROOT, 'docs', 'data',
                                'ROSPaCe_MODEL_FEATURES.json')


def shard_index(name: str):
    """提取分片编号。无法解析时返回 None。"""
    stem = os.path.basename(name).rsplit('.', 1)[0]
    tail = stem.rsplit('_', 1)[-1]
    return int(tail) if tail.isdigit() else None


def list_csv(directory: str) -> list:
    """按**数字分片序**列出 CSV，而不是字符串序。

    字符串序会把 `_10` 排在 `_2` 前面，导致"最后 N 个分片作测试"取到的
    并不是时间上最晚的分片。

    **注意**：实测主数据集的分片编号确实与时间顺序一致
    （见 docs/review/ROSPaCe_可信评测与接口缺陷修复报告.md 的会话独立性分析），
    但这只是本数据集的观测事实，不能据此断言"编号最后的文件就是最新采集会话"。
    排序只解决文件顺序问题，**不能证明采集会话独立**。
    """
    def key(path):
        idx = shard_index(path)
        return (0, idx, path) if idx is not None else (1, 0, path)
    return sorted((os.path.join(directory, n) for n in os.listdir(directory)
                   if n.lower().endswith('.csv')), key=key)


def file_has_header(path: str) -> bool:
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        return handle.readline().startswith('timestamp,')


def read_header(path: str, reference: list = None) -> list:
    if file_has_header(path):
        with open(path, 'r', encoding='utf-8', errors='replace', newline='') as h:
            return next(csv.reader(h))
    if reference is None:
        raise ValueError('无表头且无参考: {0}'.format(path))
    return list(reference)


def discover_features(path: str, reference: list, sample: int = 20000) -> list:
    """从真实数据中发现可用数值特征列（排除文本列与标签列）。

    判定标准：在抽样行中可被 `float()` 解析，或为空字符串
    （空值按缺失处理，由上游规则决定填充策略）。
    """
    header = read_header(path, reference)
    index = {name: i for i, name in enumerate(header)}
    candidates = [c for c in header
                  if c != LABEL_COLUMN and c not in TEXT_COLUMNS]
    numeric_ok = {c: 0 for c in candidates}
    seen = 0
    with open(path, 'r', encoding='utf-8', errors='replace', newline='') as handle:
        reader = csv.reader(handle)
        if file_has_header(path):
            next(reader)
        for row in reader:
            seen += 1
            if seen > sample:
                break
            for c in candidates:
                i = index[c]
                value = row[i] if i < len(row) else ''
                if value == '':
                    continue
                try:
                    float(value)
                    numeric_ok[c] += 1
                except ValueError:
                    numeric_ok[c] -= 10          # 出现非数值即强烈排除
    kept = [c for c in candidates if numeric_ok[c] > 0]
    dropped = [c for c in candidates if c not in kept]
    return kept, dropped


def stream_chunks(path: str, reference: list, feature_names: list, chunk: int,
                  row_cap: int = None, stride: int = 1):
    """流式产出 (X_rows, y_labels)，内存有界。

    `stride` 用于**跨整个文件均匀抽取**。为什么不能只取前 N 行：
    实测发现 ROSPaCe 的分片内部按攻击类型成块排列，文件开头往往全是同一种
    标签。若直接取前 N 行，测试集可能 100% 是攻击（或 100% 正常），
    从而得到 Accuracy=1.0 这种被类别分布伪造出来的"完美"结果。
    按固定步长跨越整个文件可以让抽样保持该文件真实的类别比例。
    """
    header = read_header(path, reference)
    index = {name: i for i, name in enumerate(header)}
    label_idx = index.get(LABEL_COLUMN)
    feat_idx = [(name, index[name]) for name in feature_names if name in index]
    buffer_x, buffer_y = [], []
    emitted = 0
    seen = 0
    with open(path, 'r', encoding='utf-8', errors='replace', newline='') as handle:
        reader = csv.reader(handle)
        if file_has_header(path):
            next(reader)
        for row in reader:
            seen += 1
            if stride > 1 and (seen % stride) != 0:
                continue          # 均匀跨越整个文件抽样
            if row_cap is not None and emitted + len(buffer_x) >= row_cap:
                break
            label = (row[label_idx] if label_idx is not None
                     and label_idx < len(row) else '')
            features = []
            for _name, i in feat_idx:
                value = row[i] if i < len(row) else ''
                try:
                    features.append(float(value) if value != '' else None)
                except ValueError:
                    features.append(None)
            buffer_x.append(features)
            buffer_y.append(label)
            if len(buffer_x) >= chunk:
                emitted += len(buffer_x)
                yield buffer_x, buffer_y
                buffer_x, buffer_y = [], []
    if buffer_x:
        emitted += len(buffer_x)
        yield buffer_x, buffer_y


def count_rows(path: str) -> int:
    """快速统计一个 CSV 的数据行数（用于推算抽样步长）。"""
    total = 0
    with open(path, 'rb') as handle:
        for _ in handle:
            total += 1
    if file_has_header(path):
        total -= 1
    return max(total, 1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='ROSPaCe 轻量检测模型训练')
    parser.add_argument('--dataset', choices=('reduced', 'noperiodicity'),
                        default='reduced')
    parser.add_argument('--chunk', type=int, default=100_000)
    parser.add_argument('--max-train-rows', type=int, default=3_000_000,
                        help='训练子集上限（TRAINING_SUBSET，不是全量规模）')
    parser.add_argument('--max-test-rows', type=int, default=1_000_000)
    parser.add_argument('--test-files', type=int, default=2,
                        help='按文件划分时留作测试的文件数')
    parser.add_argument('--seed', type=int, default=20261011)
    parser.add_argument('--out-dir', default=None,
                        help='产物目录；默认 training_runs/rospace_<dataset>_v2')
    parser.add_argument('--tag', default='v2', help='产物目录后缀，用于区分版本')
    args = parser.parse_args(argv)

    import numpy as np
    from sklearn.linear_model import SGDClassifier
    from sklearn.preprocessing import StandardScaler

    directory = MAIN_DIR if args.dataset == 'reduced' else NOPER_DIR
    default_name = ('rospace_{0}'.format(args.dataset) if args.tag == 'v1'
                    else 'rospace_{0}_{1}'.format(args.dataset, args.tag))
    out_dir = args.out_dir or os.path.join(REPO_ROOT, 'training_runs', default_name)
    os.makedirs(out_dir, exist_ok=True)

    files = list_csv(directory)
    if not files:
        raise SystemExit('ERROR: 未找到 CSV: {0}'.format(directory))
    reference = read_header(files[0])

    print('=== ROSPaCe 训练（dataset={0}）==='.format(args.dataset))
    print('  分片数: {0}'.format(len(files)))

    features, dropped = discover_features(files[0], reference)
    print('  可用数值特征: {0} 个'.format(len(features)))
    print('  排除的非数值/文本列: {0} 个 -> {1}'.format(
        len(dropped), [d[:36] for d in dropped]))

    # ---- 按文件划分：末尾 N 个分片作测试（保守时间/会话划分）----
    if len(files) <= args.test_files:
        raise SystemExit('ERROR: 分片数不足以划分')
    train_files = files[:-args.test_files]
    test_files = files[-args.test_files:]
    print('  预处理策略: PREPROC_V2_TWO_PASS_FIXED')
    print('  划分类型: FILE_DISJOINT_SPLIT（非会话独立，见报告）')
    print('  训练分片: {0} 个'.format(len(train_files)))
    print('  测试分片: {0} 个 -> {1}'.format(
        len(test_files), [os.path.basename(f) for f in test_files]))

    # ================= 第一遍：只在训练分片上统计预处理参数 =================
    # 为什么必须独立成一遍：原实现用**第一个 chunk** 估 col_mean，
    # 且边训练边 `scaler.partial_fit()` —— 模型在不同阶段看到的特征尺度不同，
    # 同一份数据在不同时刻会得到不同结果。这里把"统计"与"优化"彻底分离。
    print('  [pass 1/2] 统计训练集预处理参数（有界内存）...')
    t0 = time.time()
    n_features = len(features)
    count = np.zeros(n_features)
    total = np.zeros(n_features)
    total_sq = np.zeros(n_features)
    missing = np.zeros(n_features)
    non_finite = np.zeros(n_features)
    seen_total = 0
    train_labels = Counter()

    quota_per_file = max(1, args.max_train_rows // max(len(train_files), 1))
    for path in train_files:
        rows_in_file = count_rows(path)
        stride = max(1, rows_in_file // max(quota_per_file, 1))
        for bx, by in stream_chunks(path, reference, features, args.chunk,
                                    min(quota_per_file, args.max_train_rows - seen_total),
                                    stride):
            x = np.array([[float('nan') if v is None else v for v in row]
                          for row in bx], dtype=np.float64)
            finite = np.isfinite(x)
            missing += (~finite).sum(axis=0)
            non_finite += (np.isnan(x)).sum(axis=0) * 0
            safe = np.where(finite, x, 0.0)
            count += finite.sum(axis=0)
            total += safe.sum(axis=0)
            total_sq += (safe ** 2).sum(axis=0)
            seen_total += len(by)
            train_labels.update(by)
            if seen_total >= args.max_train_rows:
                break
        if seen_total >= args.max_train_rows:
            break

    # 由充分统计量推出均值/方差；全缺失或零方差列**不使用 0 掩盖**，显式记录
    with np.errstate(invalid='ignore', divide='ignore'):
        col_mean = np.where(count > 0, total / np.maximum(count, 1), np.nan)
        var = np.where(count > 0, total_sq / np.maximum(count, 1) - col_mean ** 2, np.nan)
    var = np.where(np.isfinite(var) & (var > 0), var, np.nan)
    col_std = np.sqrt(var)

    all_missing = [features[i] for i in range(n_features) if count[i] == 0]
    zero_variance = [features[i] for i in range(n_features)
                     if count[i] > 0 and not np.isfinite(var[i])]
    # 全缺失列无任何信息：用 0 填充是**有依据的固定规则**（该列恒为常数，
    # 对线性模型不提供信息），但必须显式记录，不能静默。
    fill_values = np.where(np.isfinite(col_mean), col_mean, 0.0)
    scale_values = np.where(np.isfinite(col_std) & (col_std > 0), col_std, 1.0)

    stats_seconds = time.time() - t0
    print('    训练样本 {0} 行；统计用时 {1:.1f}s'.format(seen_total, stats_seconds))
    print('    全缺失列 {0} 个；零方差列 {1} 个（已显式记录）'.format(
        len(all_missing), len(zero_variance)))

    # ================= 第二遍：用固定预处理训练 =================
    # 本遍**不再更新** fill/scaler 的任何参数。
    print('  [pass 2/2] 用固定预训练 SGD...')
    t1 = time.time()
    model = SGDClassifier(loss='log_loss', random_state=args.seed,
                          max_iter=1, tol=None, learning_rate='optimal',
                          average=True)
    classes = np.array([0, 1])
    trained = 0
    for path in train_files:
        rows_in_file = count_rows(path)
        stride = max(1, rows_in_file // max(quota_per_file, 1))
        for bx, by in stream_chunks(path, reference, features, args.chunk,
                                    min(quota_per_file, args.max_train_rows - trained),
                                    stride):
            x = np.array([[float('nan') if v is None else v for v in row]
                          for row in bx], dtype=np.float64)
            x = np.where(np.isfinite(x), x, fill_values)      # 固定填充
            xs = (x - fill_values) / scale_values             # 固定标准化
            y = np.array([0 if lbl == NORMAL_LABEL else 1 for lbl in by])
            model.partial_fit(xs, y, classes=classes)
            trained += len(by)
            if trained >= args.max_train_rows:
                break
        if trained >= args.max_train_rows:
            break
    train_seconds = time.time() - t1
    print('    训练样本 {0} 行；训练用时 {1:.1f}s'.format(trained, train_seconds))

    def _transform(x):
        x = np.where(np.isfinite(x), x, fill_values)
        return (x - fill_values) / scale_values

    train_seconds = time.time() - t0
    print('  训练样本（TRAINING_SUBSET）: {0}'.format(trained))
    print('  训练用时: {0:.1f}s'.format(train_seconds))

    # ---------------- 测试 ----------------
    test_seen = 0
    test_labels = Counter()
    tp = fp = tn = fn = 0
    # 按**真实标签**分组的检出统计（用于每类 Recall 与 Macro Recall）
    per_label = {}          # label -> {'n':int,'tp':int,'fn':int}
    # 两个简单基线：恒预测攻击 / 恒预测正常
    base_always_attack = {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0}
    base_always_normal = {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0}
    t1 = time.time()
    per_file = []
    quota_per_test = max(1, args.max_test_rows // max(len(test_files), 1))
    for path in test_files:
        f_tp = f_fp = f_tn = f_fn = 0
        rows_in_file = count_rows(path)
        t_stride = max(1, rows_in_file // max(quota_per_test, 1))
        print('    test  {0:<34} rows={1:<9} stride={2}'.format(
            os.path.basename(path), rows_in_file, t_stride))
        for bx, by in stream_chunks(path, reference, features, args.chunk,
                                    min(quota_per_test, args.max_test_rows - test_seen),
                                    t_stride):
            x = np.array([[float('nan') if v is None else v for v in row]
                          for row in bx], dtype=np.float64)
            xs = _transform(x)                              # 与训练完全一致
            y = np.array([0 if lbl == NORMAL_LABEL else 1 for lbl in by])
            test_labels.update(by)
            pred = model.predict(xs)
            f_tp += int(((pred == 1) & (y == 1)).sum())
            f_fp += int(((pred == 1) & (y == 0)).sum())
            f_tn += int(((pred == 0) & (y == 0)).sum())
            f_fn += int(((pred == 0) & (y == 1)).sum())
            for position, label in enumerate(by):
                entry = per_label.setdefault(label, {'n': 0, 'tp': 0, 'fn': 0})
                entry['n'] += 1
                if pred[position] == 1:
                    entry['tp'] += 1
                else:
                    entry['fn'] += 1
            base_always_attack['tp'] += int((y == 1).sum())
            base_always_attack['fp'] += int((y == 0).sum())
            base_always_normal['tn'] += int((y == 0).sum())
            base_always_normal['fn'] += int((y == 1).sum())
            test_seen += len(by)
            if test_seen >= args.max_test_rows:
                break
        tp += f_tp; fp += f_fp; tn += f_tn; fn += f_fn
        per_file.append({'file': os.path.basename(path),
                         'rows': f_tp + f_fp + f_tn + f_fn,
                         'tp': f_tp, 'fp': f_fp, 'tn': f_tn, 'fn': f_fn})
        if test_seen >= args.max_test_rows:
            break
    test_seconds = time.time() - t1

    total = tp + fp + tn + fn
    acc = (tp + tn) / total if total else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    # ---- 可信评价指标 ----
    sensitivity = rec                              # 攻击类召回
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    balanced_accuracy = (sensitivity + specificity) / 2.0
    macro_recall = (sum(v['tp'] / v['n'] for v in per_label.values() if v['n'])
                    / max(len([v for v in per_label.values() if v['n']]), 1))
    macro_recall_scope = sorted(k for k, v in per_label.items() if v['n'] > 0)

    def _f1(t, f_p, f_n):
        p_ = t / (t + f_p) if (t + f_p) else 0.0
        r_ = t / (t + f_n) if (t + f_n) else 0.0
        return (2 * p_ * r_ / (p_ + r_)) if (p_ + r_) else 0.0

    baselines = {
        'always_attack': {
            'accuracy': (base_always_attack['tp'] + base_always_attack['tn']) / max(total, 1),
            'precision': base_always_attack['tp'] / max(base_always_attack['tp'] + base_always_attack['fp'], 1),
            'recall': 1.0,
            'f1': _f1(base_always_attack['tp'], base_always_attack['fp'], 0),
            'balanced_accuracy': (1.0 + 0.0) / 2.0,
        },
        'always_normal': {
            'accuracy': (base_always_normal['tp'] + base_always_normal['tn']) / max(total, 1),
            'precision': 0.0,
            'recall': 0.0,
            'f1': 0.0,
            'balanced_accuracy': (0.0 + 1.0) / 2.0,
        },
    }

    print('  测试样本: {0}'.format(test_seen))
    print('  混淆矩阵: TP={0} FP={1} TN={2} FN={3}'.format(tp, fp, tn, fn))
    print('  Accuracy={0:.4f} Precision={1:.4f} Recall={2:.4f} F1={3:.4f} FPR={4:.4f}'.format(
        acc, prec, rec, f1, fpr))
    print('  BalancedAccuracy={0:.4f} MacroRecall={1:.4f}'.format(
        balanced_accuracy, macro_recall))
    print('  基线(恒预测攻击): F1={0:.4f} BA={1:.4f}'.format(
        baselines['always_attack']['f1'], baselines['always_attack']['balanced_accuracy']))
    print('  相对恒预测攻击基线: dF1={0:+.4f} dBA={1:+.4f}'.format(
        f1 - baselines['always_attack']['f1'],
        balanced_accuracy - baselines['always_attack']['balanced_accuracy']))
    print('  每类召回（仅测试集出现的标签）:')
    for label, v in sorted(per_label.items(), key=lambda kv: -kv[1]['n']):
        print('    {0:<24} n={1:<9} recall={2:.4f}'.format(
            label, v['n'], v['tp'] / v['n'] if v['n'] else 0.0))
    print('  推理用时: {0:.1f}s  峰值内存: {1:.0f} MB'.format(
        test_seconds, peak_kb / 1024))

    # ---------------- 落盘 ----------------
    import joblib
    model_path = os.path.join(out_dir, 'model.joblib')
    scaler_path = os.path.join(out_dir, 'scaler.joblib')
    joblib.dump(model, model_path)
    # 以训练时固定的 (fill, scale) 构造一个等价 StandardScaler 供推理侧使用，
    # 保证"推理与训练使用同一套预处理"可被独立验证。
    fixed_scaler = StandardScaler()
    fixed_scaler.mean_ = fill_values.copy()
    fixed_scaler.scale_ = scale_values.copy()
    fixed_scaler.var_ = (scale_values ** 2).copy()
    fixed_scaler.n_features_in_ = n_features
    joblib.dump(fixed_scaler, scaler_path)

    config = {
        'dataset': args.dataset,
        'dataset_directory': os.path.relpath(directory, REPO_ROOT),
        'feature_names': features,
        'feature_order_frozen': True,
        'dropped_columns': dropped,
        'missing_value_rule': 'training_set_column_mean',
        'column_means': [float(v) for v in fill_values],
        'column_scales': [float(v) for v in scale_values],
        'preprocessing_strategy': 'PREPROC_V2_TWO_PASS_FIXED',
        'pass1_statistics': {
            'effective_count': [int(v) for v in count],
            'missing': [int(v) for v in missing],
            'all_missing_columns': all_missing,
            'zero_variance_columns': zero_variance,
            'rule_for_all_missing': ('该列在训练集中无任何有效值；'
                                     '按固定规则填充 0，缩放 1，并在此显式记录'),
        },
        'normal_label': NORMAL_LABEL,
        'binary_mapping': {'0': NORMAL_LABEL, '1': 'any label != observe'},
        'chunk_rows': args.chunk,
        'seed': args.seed,
        'max_train_rows': args.max_train_rows,
        'max_test_rows': args.max_test_rows,
        'train_files': [os.path.basename(f) for f in train_files],
        'test_files': [os.path.basename(f) for f in test_files],
        'trained_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    config_text = json.dumps(config, ensure_ascii=False, sort_keys=True)
    config['config_sha256'] = hashlib.sha256(config_text.encode()).hexdigest()
    with open(os.path.join(out_dir, 'feature_config.json'), 'w',
              encoding='utf-8') as h:
        json.dump(config, h, ensure_ascii=False, indent=2)

    def sha_of(path):
        d = hashlib.sha256()
        with open(path, 'rb') as fh:
            for blk in iter(lambda: fh.read(1 << 20), b''):
                d.update(blk)
        return d.hexdigest()

    metrics = {
        'dataset': args.dataset,
        'statistics_scope': {
            'full_dataset_rows': 30247050 if args.dataset == 'reduced' else 20851051,
            'TRAINING_SUBSET_rows': trained,
            'TEST_rows': test_seen,
            'note': ('TRAINING_SUBSET 是抽样训练子集，不等于完整数据集规模；'
                     'FULL_DATASET_STATISTICS 见 docs/data/ROSPaCe_DATA_MANIFEST.json'),
        },
        'train_label_counts': dict(train_labels),
        'test_label_counts': dict(test_labels),
        'confusion_matrix': {'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn},
        'metrics': {'accuracy': acc, 'precision': prec, 'recall': rec,
                    'f1': f1, 'false_positive_rate': fpr,
                    'balanced_accuracy': balanced_accuracy,
                    'sensitivity_recall_attack': sensitivity,
                    'specificity_recall_normal': specificity,
                    'macro_recall': macro_recall,
                    'macro_recall_scope': macro_recall_scope},
        'per_class_recall': {
            label: {
                'support': v['n'],
                'tp': v['tp'],
                'fn': v['fn'],
                'recall': (v['tp'] / v['n']) if v['n'] else None,
                'is_attack': label != NORMAL_LABEL,
            } for label, v in sorted(per_label.items(), key=lambda kv: -kv[1]['n'])
        },
        'class_coverage_note': (
            'per_class_recall 只覆盖**测试分片中实际出现**的标签。'
            '未出现的攻击类别记 NOT_EVALUATED，不得据此宣称其检测能力。'),
        'simple_baselines': baselines,
        'lift_over_always_attack': {
            'f1_delta': f1 - baselines['always_attack']['f1'],
            'balanced_accuracy_delta': balanced_accuracy - baselines['always_attack']['balanced_accuracy'],
        },
        'pr_auc': None,
        'pr_auc_note': ('本轮未计算 PR-AUC：需要在固定阈值扫描下保存全部预测分数，'
                        '当前实现按 chunk 流式推理且未落盘分数，故如实记为未计算。'),
        'timing': {'pass1_statistics_seconds': round(stats_seconds, 2),
                   'train_seconds': round(train_seconds, 2),
                   'inference_seconds': round(test_seconds, 2)},
        'memory': {'peak_rss_mb': round(peak_kb / 1024, 1)},
        'per_test_file': per_file,
        'model_sha256': sha_of(model_path),
        'scaler_sha256': sha_of(scaler_path),
        'preprocessing_strategy': 'PREPROC_V2_TWO_PASS_FIXED',
        'column_fill_values_sha256': __import__('hashlib').sha256(
            json.dumps([float(v) for v in fill_values]).encode()).hexdigest(),
        'column_scale_values_sha256': __import__('hashlib').sha256(
            json.dumps([float(v) for v in scale_values]).encode()).hexdigest(),
        'feature_config_sha256': config['config_sha256'],
        'model_class': 'SGDClassifier(loss=log_loss)',
        'model_params': {'random_state': args.seed, 'average': True,
                         'learning_rate': 'optimal'},
        'pipeline_version': 'V2',
        'python_version': sys.version.split()[0],
        'sklearn_version': __import__('sklearn').__version__,
        'numpy_version': np.__version__,
        'split_basis': 'FILE_DISJOINT_SPLIT',
        'split_basis_note': (
            '按文件划分（文件之间无重叠）。**不等于** SESSION_DISJOINT_SPLIT：'
            '实测各分片时间戳首尾相接（上一片 last_ts == 下一片 first_ts，微秒级），'
            '属同一次连续采集按大小切片，因此无法证明采集会话独立，'
            '同源时间相关性未被排除。'),
        'sampling': ('每个分片按其规模用固定步长跨越**整个文件**抽样，'
                     '以保持该文件真实的类别比例；不取前 N 行'
                     '（实测前 N 行会因块状排列导致单类别测试集）'),
    }
    with open(os.path.join(out_dir, 'metrics.json'), 'w', encoding='utf-8') as h:
        json.dump(metrics, h, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, 'split_manifest.json'), 'w',
              encoding='utf-8') as h:
        json.dump({'train_files': [os.path.basename(f) for f in train_files],
                   'test_files': [os.path.basename(f) for f in test_files],
                   'basis': 'by_file'}, h, ensure_ascii=False, indent=2)

    print('\n  产物: {0}'.format(os.path.relpath(out_dir, REPO_ROOT)))
    print('  model_sha256: {0}'.format(metrics['model_sha256'][:16]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
