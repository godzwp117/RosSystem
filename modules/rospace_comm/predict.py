#!/usr/bin/env python3
"""ROSPaCe 检测模型离线推理入口（阶段 F2）。

安全要求（本模块的硬性约束）
----------------------------
* **不读取真实标签**决定预测结果 —— 输入记录中的 `attack` 字段会被忽略并告警。
* **字段缺失、顺序错误、模型不兼容一律安全失败**（非零退出码），
  绝不静默填 0、绝不用训练集均值长期伪造在线数据。
* 使用**训练时保存的** scaler 与列均值，不在推理时重新拟合。
* 输出模型版本与证据引用，便于溯源。

用法：
    .research-venv/bin/python modules/rospace_comm/predict.py \
        --run-dir training_runs/rospace_reduced --input records.jsonl
    .research-venv/bin/python modules/rospace_comm/predict.py \
        --run-dir training_runs/rospace_reduced --csv-row 'data/.../rospace_reduced_0.csv:1000'
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 与 train.py 保持一致的文本列定义（不进入数值特征）
TEXT_COLUMNS = ('msg_data', 'msg_type', 'src_topic', 'timestamp',
                'layers.tcp.tcp.options',
                'layers.tcp.tcp.flags_tree.tcp.flags.syn_tree._ws.expert._ws.expert.message',
                'layers._ws.short')

EXIT_OK = 0
EXIT_MISSING_MODEL = 3
EXIT_INCOMPATIBLE_INPUT = 4
EXIT_BAD_INPUT = 2

LABEL_COLUMN = 'attack'


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


class ModelArtifactError(Exception):
    """模型产物无法加载（损坏 / 格式不符 / 版本不兼容）。"""


class ModelBundle:
    """加载一次训练产物：模型、scaler、特征配置。"""

    def __init__(self, run_dir: str):
        self.run_dir = run_dir
        config_path = os.path.join(run_dir, 'feature_config.json')
        model_path = os.path.join(run_dir, 'model.joblib')
        scaler_path = os.path.join(run_dir, 'scaler.joblib')
        for path in (config_path, model_path, scaler_path):
            if not os.path.isfile(path):
                print('ERROR: 缺少训练产物 {0}。请先运行 train.py。\n'
                      '**不得在缺少模型时默认返回"正常"。**'.format(path),
                      file=sys.stderr)
                sys.exit(EXIT_MISSING_MODEL)
        try:
            import joblib
        except ImportError:
            raise SystemExit('ERROR: 需要 joblib（在隔离研究环境中安装 scikit-learn）')
        try:
            with open(config_path, encoding='utf-8') as handle:
                self.config = json.load(handle)
        except (OSError, ValueError) as exc:
            raise ModelArtifactError('feature_config.json 无法解析: {0}'.format(exc))
        try:
            self.model = joblib.load(model_path)
            self.scaler = joblib.load(scaler_path)
        except Exception as exc:              # noqa: BLE001
            # joblib 可能抛出反序列化层的任意异常；这里统一转成可识别的
            # 产物错误，让调用方 fail-closed，而不是让 traceback 穿透。
            raise ModelArtifactError('模型产物损坏或无法反序列化: {0}: {1}'.format(
                type(exc).__name__, exc))
        if not hasattr(self.model, 'predict'):
            raise ModelArtifactError('加载到的对象没有 predict 方法，不是有效模型')
        self.feature_names = list(self.config['feature_names'])
        # 训练时已明确排除的列（文本列、时间戳等）。来自原始 CSV 的输入
        # 天然带有这些列，属于**已知的非特征列**，应当容忍；
        # 只有真正未知的列才判为不兼容。
        self.known_non_features = set(self.config.get('dropped_columns') or [])
        # 训练脚本在候选阶段就排除了文本列，因此它们不会出现在 dropped_columns 里。
        # 这里必须显式并回来，否则来自原始 CSV 的行会被误判为"含未知特征"。
        self.known_non_features.update(TEXT_COLUMNS)
        self.known_non_features.update(
            {'timestamp', LABEL_COLUMN, 'msg_data', 'msg_type', 'src_topic'})
        self.column_means = list(self.config['column_means'])
        self.model_sha256 = sha256_of(model_path)
        self.config_sha256 = self.config.get('config_sha256', '')

    def validate_row(self, row: dict) -> tuple:
        """校验输入字段与顺序。返回 (ok, detail, ordered_values)。"""
        incoming = [k for k in row.keys() if k != LABEL_COLUMN]
        missing = [f for f in self.feature_names if f not in row]
        unknown = [k for k in incoming
                   if k not in self.feature_names and k not in self.known_non_features]
        if missing:
            return False, '缺少必需特征 {0} 个，例如 {1}（**不填充 0**）'.format(
                len(missing), missing[:3]), None
        if unknown:
            return False, '存在未知特征 {0} 个，例如 {1}'.format(
                len(unknown), unknown[:3]), None
        # 严格按训练时固化的顺序取值
        values = []
        for name in self.feature_names:
            raw = row[name]
            # 空串是数据集中的**合法缺失值**。训练时按 missing_value_rule
            # （training_set_column_mean）填充。推理必须用**同一规则**，
            # 而不是判为错误、更不是静默填 0。
            if raw is None or (isinstance(raw, str) and raw.strip() == ''):
                values.append(float('nan'))       # 稍后由训练集列均值填充
                continue
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                return False, '特征 {0!r} 取值无法转为数值: {1!r}'.format(name, raw), None
        return True, 'ok', values

    def predict(self, values_list: list) -> list:
        import numpy as np
        x = np.array(values_list, dtype=np.float64)
        x = np.where(np.isfinite(x), x, np.array(self.column_means))
        xs = self.scaler.transform(x)
        pred = self.model.predict(xs)
        proba = None
        if hasattr(self.model, 'predict_proba'):
            try:
                proba = self.model.predict_proba(xs)[:, 1]
            except Exception:            # noqa: BLE001
                proba = None
        return pred, proba


def rows_from_jsonl(path: str) -> list:
    rows = []
    with open(path, encoding='utf-8') as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError as exc:
                raise SystemExit('ERROR: {0}:{1} 非法 JSON: {2}'.format(path, lineno, exc))
            if not isinstance(obj, dict):
                raise SystemExit('ERROR: {0}:{1} 顶层不是对象'.format(path, lineno))
            rows.append(obj)
    return rows


def row_from_csv(path: str, lineno: int) -> dict:
    """从原始 CSV 取一行（仅用于离线复现实验，不用于在线采集）。"""
    with open(path, encoding='utf-8', errors='replace', newline='') as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if not header or not header[0].startswith('timestamp'):
            header = None                # 无表头分片
        for index, row in enumerate(reader, start=1):
            if index == lineno:
                if header is None:
                    raise SystemExit(
                        'ERROR: 该分片无表头，无法确定列名。请使用带表头的 _0 分片，'
                        '或提供 --header-from 指定参考表头。')
                return dict(zip(header, row))
    raise SystemExit('ERROR: {0} 没有第 {1} 行'.format(path, lineno))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='ROSPaCe 检测模型离线推理')
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--input', help='JSONL 输入（每条一个特征对象）')
    parser.add_argument('--csv-row', help='PATH:LINENO 形式，离线复现单行')
    parser.add_argument('--output', help='输出 JSONL 路径；缺省打印到 stdout')
    parser.add_argument('--basis', default='ROSPaCe 公开数据集离线特征',
                        help='写入 evidence 的 basis 说明')
    args = parser.parse_args(argv)

    if not args.input and not args.csv_row:
        parser.error('需要 --input 或 --csv-row')

    bundle = ModelBundle(args.run_dir)

    if args.input:
        records = rows_from_jsonl(args.input)
        source = os.path.relpath(args.input, REPO_ROOT)
    else:
        path, _, lineno = args.csv_row.rpartition(':')
        if not path:
            raise SystemExit('ERROR: --csv-row 需要 PATH:LINENO 形式')
        records = [row_from_csv(path, int(lineno))]
        source = '{0}:{1}'.format(os.path.relpath(path, REPO_ROOT), lineno)

    validated, errors = [], []
    for index, record in enumerate(records):
        if LABEL_COLUMN in record:
            print('[warn] 第 {0} 条输入含标签列 {1!r}，已**忽略**（不得由标签决定预测）'.format(
                index + 1, LABEL_COLUMN), file=sys.stderr)
            record = {k: v for k, v in record.items() if k != LABEL_COLUMN}
        ok, detail, values = bundle.validate_row(record)
        if ok:
            validated.append((index, values))
        else:
            errors.append({'index': index, 'error': detail})

    if errors:
        print(json.dumps({
            'status': 'INPUT_INCOMPATIBLE',
            'errors': errors[:5],
            'note': ('字段不满足训练时的特征契约。**不填充 0、不用均值伪造**，'
                     '直接失败。'),
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return EXIT_INCOMPATIBLE_INPUT

    preds, probas = bundle.predict([v for _i, v in validated])
    results = []
    for position, (index, _values) in enumerate(validated):
        results.append({
            'index': index,
            'prediction': int(preds[position]),
            'prediction_label': 'attack' if int(preds[position]) == 1 else 'normal',
            'attack_probability': (round(float(probas[position]), 6)
                                   if probas is not None else None),
        })

    payload = {
        'model_version': {
            'run_dir': os.path.relpath(bundle.run_dir, REPO_ROOT),
            'model_sha256': bundle.model_sha256,
            'feature_config_sha256': bundle.config_sha256,
            'model_class': bundle.config.get('model_class', 'SGDClassifier'),
            'trained_dataset': bundle.config.get('dataset'),
        },
        'evidence_refs': [{
            'ref': source,
            'kind': 'OFFLINE_DATASET_FEATURE',
            'basis': args.basis,
            'note': ('来源为 ROSPaCe 公开数据集的离线特征行，'
                     '**不是** ROS 2 实时采集数据，也不是 DDS 身份认证证据。'),
        }],
        'feature_count': len(bundle.feature_names),
        'records': results,
        'online_capability': {
            'status': 'NOT_READY',
            'reason': ('本模型输入含大量需 PCAP 抓包或新增采集器的特征，'
                       '当前不具备 Jazzy 在线获取能力；'
                       '详见 docs/data/ROSPaCe_JAZZY_FEATURE_FEASIBILITY.csv'),
        },
    }
    text = json.dumps(payload, ensure_ascii=False)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as handle:
            handle.write(text + '\n')
        print('已写出 {0}（{1} 条预测）'.format(args.output, len(results)))
    else:
        print(text)
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
