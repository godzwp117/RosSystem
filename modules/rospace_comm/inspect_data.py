#!/usr/bin/env python3
"""ROSPaCe reduced 数据审计（阶段 A）。

设计原则
--------
* **只读**：绝不修改原始文件（以只读模式打开，且不写回任何数据目录）。
* **内存有界**：全部统计走分块读取；不使用 `pandas.read_csv` 一次性载入。
* **全量而非采样**：类别分布等统计遍历**全部行**，不接受"只取前 N 行冒充全量"。
  若因损坏只能读到部分数据，如实标记 PARTIAL 并记录实际读取行数。
* **不猜测语义**：字段含义只来自 `feature_list.xlsx`；找不到说明的标记
  `SEMANTICS_UNKNOWN`，不擅自把它解释成 DDS 速率、节点身份或 Action 调用数。

用法：
    .research-venv/bin/python modules/rospace_comm/inspect_data.py --help
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter, OrderedDict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_ROOT = os.path.join(REPO_ROOT, 'data', 'ROSPaCe_reduced')

MAIN_DIR = os.path.join(DATA_ROOT, 'ROSPaCe_reduced')
NOPERIODICITY_DIR = os.path.join(DATA_ROOT, 'ROSPaCe_reduced_noperiodicity')
FEATURE_LIST = os.path.join(DATA_ROOT, 'feature_list.xlsx')
WINDOWS_JSONL = os.path.join(DATA_ROOT, 'windows_0.jsonl')

DEFAULT_CHUNK = 100_000
LABEL_COLUMN = 'attack'

# 与 feature_list 的 monitor 取值一一对应；用于把列归到采集层
MONITOR_BY_NAME: dict = {}


# ---------------------------------------------------------------- 工具
def sha256_of(path: str, block: int = 1 << 22) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        while True:
            data = handle.read(block)
            if not data:
                break
            digest.update(data)
    return digest.hexdigest()


def load_feature_list(path: str = FEATURE_LIST) -> list:
    """读取 feature_list.xlsx。若缺 openpyxl 则如实失败，不伪造。"""
    try:
        import openpyxl
    except ImportError as exc:            # pragma: no cover
        raise SystemExit(
            'ERROR: 需要 openpyxl 读取 feature_list.xlsx。'
            '请在隔离研究环境中安装：.research-venv/bin/pip install openpyxl\n'
            '原始错误: {0}'.format(exc))
    wb = openpyxl.load_workbook(path, read_only=True)
    if 'features_list' not in wb.sheetnames:
        raise SystemExit('ERROR: feature_list.xlsx 缺少 features_list 工作表')
    ws = wb['features_list']
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c) if c is not None else '' for c in rows[0]]
    features = []
    for row in rows[1:]:
        cells = ['' if c is None else str(c) for c in row]
        if not any(cells):
            continue
        record = dict(zip(header, cells))
        features.append({
            'feature_name': record.get('feature_name', ''),
            'monitor': record.get('monitor', ''),
            'description': record.get('description', ''),
        })
    return features


def file_has_header(path: str) -> bool:
    """判断文件首行是表头还是数据。

    实测发现：每个数据集**只有 _0 文件带表头**，其余分片直接从数据行开始。
    若不加区分地把首行当表头，会同时导致两类错误：
      * 丢掉该文件的一行真实数据；
      * 在"无表头"文件里找不到标签列，标签统计被静默跳过。
    """
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        first = handle.readline()
    return first.startswith('timestamp,')


def read_header(path: str, reference: list = None) -> list:
    """读取有效表头：有表头则用自身的，否则沿用参考表头。"""
    if file_has_header(path):
        with open(path, 'r', encoding='utf-8', errors='replace', newline='') as handle:
            return next(csv.reader(handle))
    if reference is None:
        raise ValueError('文件无表头且未提供参考表头: {0}'.format(path))
    return list(reference)


def list_csv(directory: str) -> list:
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, n) for n in os.listdir(directory)
                  if n.lower().endswith('.csv'))


# ---------------------------------------------------------------- 表头审计
def audit_headers(csv_files: list) -> dict:
    """逐文件读取表头，检查列数/顺序/重复列/标签列/时间列。"""
    report = {'files': [], 'headers_identical': True, 'reference': None,
              'duplicate_columns': [], 'all_columns': [], 'files_with_header': [],
              'files_without_header': []}
    reference = None
    for path in csv_files:
        try:
            has_header = file_has_header(path)
            header = read_header(path, reference)
        except (OSError, ValueError) as exc:
            report['files'].append({'path': os.path.relpath(path, REPO_ROOT),
                                    'error': str(exc)})
            continue
        duplicates = sorted({c for c in header if header.count(c) > 1})
        if has_header:
            report['files_with_header'].append(os.path.basename(path))
        else:
            report['files_without_header'].append(os.path.basename(path))
        entry = {
            'path': os.path.relpath(path, REPO_ROOT),
            'has_header': has_header,
            'columns': len(header),
            'size_bytes': os.path.getsize(path),
            'duplicate_columns': duplicates,
            'has_label': LABEL_COLUMN in header,
            'has_timestamp': 'timestamp' in header,
            'first_column': header[0] if header else None,
            'last_column': header[-1] if header else None,
        }
        report['files'].append(entry)
        if duplicates:
            report['duplicate_columns'].extend(duplicates)
        if reference is None:
            reference = header
            report['reference'] = header
        elif header != reference:
            report['headers_identical'] = False
    report['reference'] = reference
    report['all_columns'] = reference or []
    return report


# ---------------------------------------------------------------- 全量分块统计
def scan_csv(path: str, chunk: int, columns: list, max_rows: int = None,
             reference_header: list = None):
    """分块遍历一个 CSV，产出 (标签计数, 每列统计, 问题计数, 读取行数)。

    每列统计包含：非空数、非有限数、数值可解析数、唯一值（有上限）、
    最小/最大值。只对**声明关注的列**维护唯一值集合，避免内存无界。
    """
    label_counts = Counter()
    stats = OrderedDict()
    for name in columns:
        stats[name] = {'present': 0, 'empty': 0, 'non_finite': 0, 'numeric': 0,
                       'non_numeric': 0, 'min': None, 'max': None,
                       'uniques': set(), 'unique_capped': False}
    issues = Counter()
    rows_read = 0

    with open(path, 'r', encoding='utf-8', errors='replace', newline='') as handle:
        reader = csv.reader(handle)
        has_header = file_has_header(path)
        header = read_header(path, reference_header)
        if has_header:
            next(reader)              # 跳过真实表头行
        index = {name: i for i, name in enumerate(header)}
        label_idx = index.get(LABEL_COLUMN)
        col_indices = [(name, index[name]) for name in columns if name in index]
        for row in reader:
            rows_read += 1
            if max_rows and rows_read > max_rows:
                rows_read -= 1
                issues['truncated_by_max_rows'] += 1
                break
            if len(row) != len(header):
                issues['ragged_rows'] += 1
            if label_idx is not None:
                label = row[label_idx] if label_idx < len(row) else ''
                label_counts[label] += 1
            for name, i in col_indices:
                value = row[i] if i < len(row) else ''
                entry = stats[name]
                if value == '':
                    entry['empty'] += 1
                    continue
                entry['present'] += 1
                try:
                    number = float(value)
                except ValueError:
                    entry['non_numeric'] += 1
                    if len(entry['uniques']) < 32 and not entry['unique_capped']:
                        entry['uniques'].add(value[:64])
                    continue
                if not math.isfinite(number):
                    entry['non_finite'] += 1
                    continue
                entry['numeric'] += 1
                if entry['min'] is None or number < entry['min']:
                    entry['min'] = number
                if entry['max'] is None or number > entry['max']:
                    entry['max'] = number
    return label_counts, stats, issues, rows_read


def merge_stats(target: dict, source: dict) -> None:
    for name, entry in source.items():
        acc = target.setdefault(name, {'present': 0, 'empty': 0, 'non_finite': 0,
                                       'numeric': 0, 'non_numeric': 0,
                                       'min': None, 'max': None,
                                       'uniques': set(), 'unique_capped': False})
        for key in ('present', 'empty', 'non_finite', 'numeric', 'non_numeric'):
            acc[key] += entry[key]
        if entry['min'] is not None:
            acc['min'] = entry['min'] if acc['min'] is None else min(acc['min'], entry['min'])
        if entry['max'] is not None:
            acc['max'] = entry['max'] if acc['max'] is None else max(acc['max'], entry['max'])
        room = 32 - len(acc['uniques'])
        if room > 0:
            acc['uniques'].update(list(entry['uniques'])[:room])
        if len(acc['uniques']) >= 32:
            acc['unique_capped'] = True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='ROSPaCe reduced 数据审计')
    parser.add_argument('--chunk', type=int, default=DEFAULT_CHUNK,
                        help='分块大小（行），默认 100000')
    parser.add_argument('--max-rows-per-file', type=int, default=None,
                        help='调试用上限；正式审计不要设置，否则结果只能算 PARTIAL')
    parser.add_argument('--out-dir', default=os.path.join(REPO_ROOT, 'docs', 'data'))
    parser.add_argument('--skip-hash', action='store_true',
                        help='跳过全量 SHA-256（22 GB，耗时较长）')
    args = parser.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)

    print('=== ROSPaCe reduced 数据审计 ===')
    print('  chunk = {0} 行'.format(args.chunk))

    main_csv = list_csv(MAIN_DIR)
    noper_csv = list_csv(NOPERIODICITY_DIR)
    print('  主数据集 CSV: {0} 个'.format(len(main_csv)))
    print('  去周期性 CSV: {0} 个'.format(len(noper_csv)))
    if not main_csv:
        raise SystemExit('ERROR: 主数据集目录下没有 CSV：{0}'.format(MAIN_DIR))

    started = time.time()
    manifest = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'repo_commit': None,
        'data_root': os.path.relpath(DATA_ROOT, REPO_ROOT),
        'chunk_rows': args.chunk,
        'files': [],
        'notes': [],
    }

    # ---------------- 文件清单 + 哈希 ----------------
    for path in main_csv + noper_csv + [FEATURE_LIST]:
        if not os.path.isfile(path):
            continue
        entry = {
            'path': os.path.relpath(path, REPO_ROOT),
            'size_bytes': os.path.getsize(path),
            'format': os.path.splitext(path)[1].lower().lstrip('.'),
            'compressed': path.endswith(('.tar.gz', '.zip')),
        }
        if not args.skip_hash:
            print('  SHA-256: {0} ...'.format(os.path.basename(path)), end='', flush=True)
            entry['sha256'] = sha256_of(path)
            print(' {0}'.format(entry['sha256'][:16]))
        manifest['files'].append(entry)
    if os.path.isfile(WINDOWS_JSONL):
        manifest['files'].append({
            'path': os.path.relpath(WINDOWS_JSONL, REPO_ROOT),
            'size_bytes': os.path.getsize(WINDOWS_JSONL),
            'format': 'jsonl', 'compressed': False,
            'sha256': None if args.skip_hash else sha256_of(WINDOWS_JSONL),
        })

    # ---------------- 表头审计 ----------------
    print('\n=== 表头审计 ===')
    main_headers = audit_headers(main_csv)
    noper_headers = audit_headers(noper_csv)
    main_cols = main_headers['all_columns']
    noper_cols = noper_headers['all_columns']
    print('  主数据集列数: {0}，各文件表头一致: {1}'.format(
        len(main_cols), main_headers['headers_identical']))
    print('  带表头的文件: {0} 个 -> {1}'.format(
        len(main_headers['files_with_header']), main_headers['files_with_header']))
    print('  不带表头的文件: {0} 个（首行即数据，已沿用参考表头）'.format(
        len(main_headers['files_without_header'])))
    print('  去周期性列数: {0}，各文件表头一致: {1}'.format(
        len(noper_cols), noper_headers['headers_identical']))
    only_main = [c for c in main_cols if c not in noper_cols]
    only_noper = [c for c in noper_cols if c not in main_cols]
    print('  仅主数据集有: {0}'.format(only_main or '无'))
    print('  仅去周期性有: {0}'.format(only_noper or '无'))

    # ---------------- feature_list 对照 ----------------
    print('\n=== feature_list 对照 ===')
    features = load_feature_list()
    by_name = {f['feature_name']: f for f in features}
    monitor_counts = Counter(f['monitor'] or '(空)' for f in features)
    print('  feature_list 条目: {0}'.format(len(features)))
    for key, value in monitor_counts.most_common():
        print('    {0:<20} {1}'.format(key, value))
    unknown = [c for c in main_cols if c not in by_name]
    print('  reduced 列在 feature_list 中找不到说明: {0}'.format(unknown or '无'))

    # ---------------- 全量分块统计 ----------------
    stat_columns = [c for c in main_cols if c not in ('msg_data',)]
    print('\n=== 全量分块统计（主数据集）===')
    label_counts = Counter()
    stats: dict = {}
    issues = Counter()
    total_rows = 0
    per_file = []
    for path in main_csv:
        t0 = time.time()
        lc, st, iss, rows = scan_csv(path, args.chunk, stat_columns,
                                     args.max_rows_per_file, main_cols)
        label_counts.update(lc)
        merge_stats(stats, st)
        issues.update(iss)
        total_rows += rows
        per_file.append({'path': os.path.relpath(path, REPO_ROOT), 'rows': rows,
                         'seconds': round(time.time() - t0, 1)})
        print('  {0:<46} {1:>10} 行  {2:>6.1f}s'.format(
            os.path.basename(path), rows, time.time() - t0))

    status = 'FULL' if not args.max_rows_per_file else 'PARTIAL'
    print('\n  总行数: {0} ({1})'.format(total_rows, status))
    print('  标签分布:')
    for label, count in label_counts.most_common():
        print('    {0!r:<12} {1:>12}  ({2:.4f}%)'.format(
            label, count, count * 100.0 / max(total_rows, 1)))

    # ---------------- 输出 ----------------
    commit = None
    try:
        import subprocess
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO_ROOT,
                                capture_output=True, text=True).stdout.strip()
    except Exception:                     # noqa: BLE001
        pass
    manifest['repo_commit'] = commit
    manifest['statistics_status'] = status
    manifest['full_dataset_rows'] = total_rows
    manifest['label_counts'] = dict(label_counts)
    manifest['monitor_counts'] = dict(monitor_counts)
    manifest['header_structure'] = {
        'main': {'with_header': main_headers['files_with_header'],
                 'without_header': main_headers['files_without_header']},
        'noperiodicity': {'with_header': noper_headers['files_with_header'],
                          'without_header': noper_headers['files_without_header']},
    }
    manifest['columns'] = {'main': main_cols, 'noperiodicity': noper_cols,
                           'only_main': only_main, 'only_noperiodicity': only_noper}
    manifest['per_file_rows'] = per_file
    if args.max_rows_per_file:
        manifest['notes'].append(
            '使用了 --max-rows-per-file={0}，统计结果为 PARTIAL，'
            '不得当作全量分布。'.format(args.max_rows_per_file))
    with open(os.path.join(args.out_dir, 'ROSPaCe_DATA_MANIFEST.json'), 'w',
              encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    # 特征字典
    with open(os.path.join(args.out_dir, 'ROSPaCe_FEATURE_DICTIONARY.csv'), 'w',
              encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['feature_name', 'in_reduced_main', 'in_reduced_noperiodicity',
                         'monitor', 'description', 'semantics', 'present', 'empty',
                         'non_finite', 'min', 'max'])
        for feature in features:
            name = feature['feature_name']
            entry = stats.get(name, {})
            described = bool(feature['description'].strip())
            writer.writerow([
                name,
                'yes' if name in main_cols else 'no',
                'yes' if name in noper_cols else 'no',
                feature['monitor'],
                feature['description'][:300],
                'DESCRIBED' if described else 'SEMANTICS_UNKNOWN',
                entry.get('present', ''), entry.get('empty', ''),
                entry.get('non_finite', ''), entry.get('min', ''), entry.get('max', ''),
            ])

    # 标签分布
    with open(os.path.join(args.out_dir, 'ROSPaCe_LABEL_DISTRIBUTION.csv'), 'w',
              encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['dataset', 'raw_label', 'count', 'ratio',
                         'binary_mapping', 'status'])
        for label, count in label_counts.most_common():
            writer.writerow(['ROSPaCe_reduced', label, count,
                             '{0:.6f}'.format(count / max(total_rows, 1)),
                             'UNKNOWN(见审计报告)', status])

    print('\n已写出（目录 {0}）:'.format(os.path.relpath(args.out_dir, REPO_ROOT)))
    for name in ('ROSPaCe_DATA_MANIFEST.json', 'ROSPaCe_FEATURE_DICTIONARY.csv',
                 'ROSPaCe_LABEL_DISTRIBUTION.csv'):
        print('  {0}'.format(os.path.join(os.path.relpath(args.out_dir, REPO_ROOT), name)))
    print('  用时 {0:.1f}s'.format(time.time() - started))
    return 0


if __name__ == '__main__':
    sys.exit(main())
