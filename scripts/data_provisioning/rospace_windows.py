#!/usr/bin/env python3
"""从 ROSPaCe 精简版 CSV 按 (session, block, topic) 抽取窗口证据。

为什么需要它
------------
直接用整个 CSV 做统计会得到一个跨越数小时的巨大"窗口"，其结论没有意义
（真实数据实测：`/rosout` 的 p95/中位数 高达 15668，任何话题都会被误判为抖动异常）。

ROSPaCe 的采集脚本是「30 s 正常 → 攻击 ≤60 s → 10 s 恢复」交替执行 400 次，
因此**正确的切分单位是 block（正常段 + 紧随的攻击段）**，这也与作者
`usage_note_B_detection_time_series` 的划分方式一致。

本脚本只读取数据、只做统计与落盘，不发送任何网络流量。

用法
----
    python3 scripts/data_provisioning/rospace_windows.py \
        --csv data/ROSPaCe_reduced/ROSPaCe_reduced/rospace_reduced_0.csv \
        --out data/ROSPaCe_reduced/windows_0.jsonl \
        --min-gap-s 20               # 判定"新采集段"的时间间隔阈值
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from collections import Counter

SCHEMA_VERSION = "1.0.0-proposed"
TIME_COL = "timestamp"
TOPIC_COL = "src_topic"
LABEL_COL = "attack"


def parse_time(raw: str):
    """解析 ROSPaCe 的 9 位纳秒小数秒时间戳（%f 只支持 1–6 位）。"""
    raw = (raw or "").strip().strip('"')
    if not raw:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?$", raw)
    if not m:
        return None
    y, mo, d, hh, mm, ss = (int(g) for g in m.groups()[:6])
    frac = m.group(7) or ""
    base = _dt.datetime(y, mo, d, hh, mm, ss, tzinfo=_dt.timezone.utc).timestamp()
    return base + (float("0." + frac) if frac else 0.0)


def rfc3339(ts: float) -> str:
    return (_dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
            .isoformat().replace("+00:00", "Z"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ROSPaCe 精简版 → 按 block 的窗口证据 JSONL")
    ap.add_argument("--csv", required=True, help="rospace_reduced_*.csv 之一")
    ap.add_argument("--out", required=True, help="输出 JSONL 路径")
    ap.add_argument("--min-gap-s", type=float, default=20.0,
                    help="相邻样本间隔超过该值即认为进入新的采集段（默认 20 s）")
    ap.add_argument("--min-block-rows", type=int, default=50,
                    help="样本数低于该值的 block 不产出结论（避免小样本噪声）")
    ap.add_argument("--top-topics", type=int, default=30,
                    help="每个 block 最多输出样本数前 N 的话题")
    args = ap.parse_args(argv)

    # ---------- 读取 ----------
    recs = []  # (t, topic, label)
    skipped = 0
    labels = Counter()
    with open(args.csv, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        need = {TIME_COL, TOPIC_COL, LABEL_COL}
        missing = need - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"{args.csv} 缺少必需列：{sorted(missing)}")
        for row in reader:
            t = parse_time(row.get(TIME_COL))
            if t is None:
                skipped += 1
                continue
            label = (row.get(LABEL_COL) or "").strip()
            labels[label] += 1
            recs.append((t, (row.get(TOPIC_COL) or "").strip(), label))

    if not recs:
        raise SystemExit("没有解析到任何样本")

    recs.sort(key=lambda x: x[0])
    print(f"解析 {len(recs)} 行（跳过 {skipped} 行），标签 {len(labels)} 种", file=sys.stderr)

    # ---------- 切分采集段 ----------
    segments = []
    cur = [recs[0]]
    for prev, item in zip(recs, recs[1:]):
        if item[0] - prev[0] > args.min_gap_s:
            segments.append(cur)
            cur = []
        cur.append(item)
    segments.append(cur)
    print(f"按间隔 > {args.min_gap_s}s 切出 {len(segments)} 个采集段", file=sys.stderr)

    # ---------- 段内切 block（标签变化即新 block）----------
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    n_blocks = n_out = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for si, seg in enumerate(segments):
            block = []
            prev_label = None
            for item in seg:
                if prev_label is not None and item[2] != prev_label:
                    n_blocks += 1
                    n_out += emit(out, si, n_blocks, block, args)
                    block = []
                block.append(item)
                prev_label = item[2]
            if block:
                n_blocks += 1
                n_out += emit(out, si, n_blocks, block, args)

    print(f"共 {n_blocks} 个 block，写出 {n_out} 条窗口记录 → {args.out}", file=sys.stderr)
    print("注意：本文件是【数据源原生标签】的窗口划分产物，"
          "不含任何本项目安全的结论；异常判定请另行基于基线执行。", file=sys.stderr)
    return 0


def emit(out, seg_idx, block_idx, block, args):
    """把一个 block 内每个话题汇成一条记录。"""
    if len(block) < args.min_block_rows:
        return 0
    by_topic = {}
    for t, topic, label in block:
        by_topic.setdefault(topic, []).append(t)

    start = min(b[0] for b in block)
    end = max(b[0] for b in block)
    window_ms = (end - start) * 1000.0
    label = block[0][2]
    written = 0

    for topic, times in sorted(by_topic.items(), key=lambda kv: -len(kv[1]))[:args.top_topics]:
        times.sort()
        n = len(times)
        spans = [times[i + 1] - times[i] for i in range(n - 1)]
        median_ms = p95_ms = max_ms = None
        if spans:
            s = sorted(spans)
            median_ms = s[len(s) // 2] * 1000.0
            p95_ms = s[min(len(s) - 1, int(0.95 * len(s)))] * 1000.0
            max_ms = s[-1] * 1000.0
        rec = {
            "segment_index": seg_idx,
            "block_index": block_idx,
            "source_label": label,          # 数据源原生标签
            "schema_version": SCHEMA_VERSION,
            "communication": {"resource": topic or "(未标注话题)",
                              "resource_type": "Topic",
                              "operation": "PUBLISH"},
            "window": {"start": rfc3339(start), "end": rfc3339(end),
                       "duration_ms": round(window_ms, 3)},
            "request_count": n,
            "frequency_hz": round((n - 1) / (window_ms / 1000.0), 6) if window_ms > 0 else None,
            "gap_median_ms": round(median_ms, 3) if median_ms is not None else None,
            "gap_p95_ms": round(p95_ms, 3) if p95_ms is not None else None,
            "gap_max_ms": round(max_ms, 3) if max_ms is not None else None,
            "_provenance": {
                "note": "窗口划分与统计由本脚本产生；source_label 为数据源原生标签，"
                        "不是本项目的安全结论。",
                "source_file": os.path.basename(args.csv),
            },
        }
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        written += 1
    return written


if __name__ == "__main__":
    sys.exit(main())
