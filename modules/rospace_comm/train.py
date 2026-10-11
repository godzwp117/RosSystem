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


def list_csv(directory: str) -> list:
    return sorted(os.path.join(directory, n) for n in os.listdir(directory)
                  if n.lower().endswith('.csv'))


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
    parser.add_argument('--out-dir', default=None)
    args = parser.parse_args(argv)

    import numpy as np
    from sklearn.linear_model import SGDClassifier
    from sklearn.preprocessing import StandardScaler

    directory = MAIN_DIR if args.dataset == 'reduced' else NOPER_DIR
    out_dir = args.out_dir or os.path.join(
        REPO_ROOT, 'training_runs', 'rospace_{0}'.format(args.dataset))
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
    print('  训练分片: {0} 个'.format(len(train_files)))
    print('  测试分片: {0} 个 -> {1}'.format(
        len(test_files), [os.path.basename(f) for f in test_files]))

    # ---------------- 训练集拟合（scaler 与模型）----------------
    scaler = StandardScaler()
    model = SGDClassifier(loss='log_loss', random_state=args.seed,
                          max_iter=1, tol=None, learning_rate='optimal',
                          average=True)
    classes = np.array([0, 1])

    train_seen = 0
    train_labels = Counter()
    t0 = time.time()
    first_pass = True
    # 每个训练分片按其规模分配配额，并跨越整个文件抽样，避免只吃到文件开头
    quota_per_file = max(1, args.max_train_rows // max(len(train_files), 1))
    for path in train_files:
        rows_in_file = count_rows(path)
        stride = max(1, rows_in_file // max(quota_per_file, 1))
        print('    train {0:<34} rows={1:<9} stride={2}'.format(
            os.path.basename(path), rows_in_file, stride))
        for bx, by in stream_chunks(path, reference, features, args.chunk,
                                    min(quota_per_file, args.max_train_rows - train_seen),
                                    stride):
            x = np.array([[float('nan') if v is None else v for v in row]
                          for row in bx], dtype=np.float64)
            # 缺失值用训练集列均值填充；均值只在训练集上估计（第一遍）
            if first_pass:
                col_mean = np.nanmean(x, axis=0)
                col_mean = np.where(np.isfinite(col_mean), col_mean, 0.0)
            x = np.where(np.isfinite(x), x, col_mean)
            y = np.array([0 if lbl == NORMAL_LABEL else 1 for lbl in by])
            train_labels.update(by)
            scaler.partial_fit(x)
            xs = scaler.transform(x)
            model.partial_fit(xs, y, classes=classes)
            first_pass = False
            train_seen += len(by)
            if train_seen >= args.max_train_rows:
                break
        if train_seen >= args.max_train_rows:
            break
    train_seconds = time.time() - t0
    print('  训练样本（TRAINING_SUBSET）: {0}'.format(train_seen))
    print('  训练用时: {0:.1f}s'.format(train_seconds))

    # ---------------- 测试 ----------------
    test_seen = 0
    test_labels = Counter()
    tp = fp = tn = fn = 0
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
            x = np.where(np.isfinite(x), x, col_mean)
            xs = scaler.transform(x)
            y = np.array([0 if lbl == NORMAL_LABEL else 1 for lbl in by])
            test_labels.update(by)
            pred = model.predict(xs)
            f_tp += int(((pred == 1) & (y == 1)).sum())
            f_fp += int(((pred == 1) & (y == 0)).sum())
            f_tn += int(((pred == 0) & (y == 0)).sum())
            f_fn += int(((pred == 0) & (y == 1)).sum())
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

    print('  测试样本: {0}'.format(test_seen))
    print('  混淆矩阵: TP={0} FP={1} TN={2} FN={3}'.format(tp, fp, tn, fn))
    print('  Accuracy={0:.4f} Precision={1:.4f} Recall={2:.4f} F1={3:.4f} FPR={4:.4f}'.format(
        acc, prec, rec, f1, fpr))
    print('  推理用时: {0:.1f}s  峰值内存: {1:.0f} MB'.format(
        test_seconds, peak_kb / 1024))

    # ---------------- 落盘 ----------------
    import joblib
    model_path = os.path.join(out_dir, 'model.joblib')
    scaler_path = os.path.join(out_dir, 'scaler.joblib')
    joblib.dump(model, model_path)
    joblib.dump(scaler, scaler_path)

    config = {
        'dataset': args.dataset,
        'dataset_directory': os.path.relpath(directory, REPO_ROOT),
        'feature_names': features,
        'feature_order_frozen': True,
        'dropped_columns': dropped,
        'missing_value_rule': 'training_set_column_mean',
        'column_means': [float(v) for v in col_mean],
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
            'TRAINING_SUBSET_rows': train_seen,
            'TEST_rows': test_seen,
            'note': ('TRAINING_SUBSET 是抽样训练子集，不等于完整数据集规模；'
                     'FULL_DATASET_STATISTICS 见 docs/data/ROSPaCe_DATA_MANIFEST.json'),
        },
        'train_label_counts': dict(train_labels),
        'test_label_counts': dict(test_labels),
        'confusion_matrix': {'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn},
        'metrics': {'accuracy': acc, 'precision': prec, 'recall': rec,
                    'f1': f1, 'false_positive_rate': fpr},
        'timing': {'train_seconds': round(train_seconds, 2),
                   'inference_seconds': round(test_seconds, 2)},
        'memory': {'peak_rss_mb': round(peak_kb / 1024, 1)},
        'per_test_file': per_file,
        'model_sha256': sha_of(model_path),
        'scaler_sha256': sha_of(scaler_path),
        'feature_config_sha256': config['config_sha256'],
        'model_class': 'SGDClassifier(loss=log_loss)',
        'model_params': {'random_state': args.seed, 'average': True,
                         'learning_rate': 'optimal'},
        'split_basis': 'by_file (每个分片为独立采集时段；无虚构 group_id)',
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
