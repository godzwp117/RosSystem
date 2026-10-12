#!/usr/bin/env python3
"""从 RTPS/PCAP 或 HCRL 标注 CSV 提取 CommRiskEvidence（契约版本 1.0.0-proposed）。

设计约束（来自 docs/interfaces/CONTRACT_VERSION.md 八条安全边界）：
  * 规则一：producer / node_name 等自报字段不是认证凭据；本工具不产出身份认证结论。
  * 规则六：evidence_refs.kind 必须如实标注来源等级。本工具对公开数据集标注
            CONTROLLED_SECURITY_EXPERIMENT（数据集作者做的受控攻击实验），
            对本地自采数据标注 RUNTIME_LOG，绝不标 unit_test / mock。
  * 未知字段一律不填，不用 0 或占位常量冒充（如 frequency_hz 无法计算时直接省略）。

本脚本只读取数据、只做统计与规则判定，不发送任何网络流量。
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter

SCHEMA_VERSION = "1.0.0-proposed"

# --- 契约允许的枚举（必须与 docs/interfaces/schemas/ 完全一致） -------------
RESOURCE_TYPES = ("Topic", "Service", "Action")
OPERATIONS = (
    "PUBLISH", "SUBSCRIBE", "SERVICE_REQUEST", "SERVICE_REPLY",
    "GOAL_SEND", "GOAL_ACCEPT", "CANCEL", "UNKNOWN",
)
ANOMALY_CATEGORIES = (
    "NONE", "REQUEST_RATE_ANOMALY", "DUPLICATE_CALL_PATTERN",
    "TIMING_DEVIATION", "UNEXPECTED_RESOURCE_ACCESS",
    "NODE_RELATION_ANOMALY", "UNKNOWN",
)
RISK_LEVELS = ("NONE", "LOW", "MEDIUM", "HIGH", "UNKNOWN")
STATUSES = ("NORMAL", "SUSPICIOUS", "UNKNOWN", "ERROR")

MAX_DURATION_MS = 24 * 60 * 60 * 1000  # 契约规定上界 24 小时

# RTPS 子消息 id → 可读名（仅用于 basis 文本）
RTPS_SM_NAMES = {
    "0x01": "PAD", "0x02": "ACKNACK", "0x03": "HEARTBEAT", "0x06": "GAP",
    "0x07": "INFO_TS", "0x08": "INFO_SRC", "0x09": "INFO_DST",
    "0x0a": "INFO_REPLY", "0x0b": "INFO_REPLY_IP4", "0x0c": "NACK_FRAG",
    "0x0d": "HEARTBEAT_FRAG", "0x0e": "DATA_FRAG", "0x15": "DATA",
    "0x80": "vendor-specific",
}


def _rfc3339(ts: float) -> str:
    """UTC RFC 3339，含时区。契约要求必须带时区。"""
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(raw: str):
    """把多种时间表示解析成 Unix 秒。支持 epoch（s/ms/us/ns）与日期时间字符串。

    真实数据集格式差异较大，例如 ROSPaCe 使用 9 位纳秒小数秒
    （``2023-03-16 14:22:23.903192576``），而 ``%f`` 只接受 1–6 位，
    因此这里不依赖 strptime 解析小数部分。
    """
    raw = raw.strip().strip('"').strip()
    if not raw:
        return None

    # 1) 纯数字 → 按量级判断单位
    try:
        val = float(raw)
    except ValueError:
        val = None
    if val is not None:
        if val > 1e17:
            val /= 1e9
        elif val > 1e14:
            val /= 1e6
        elif val > 1e11:
            val /= 1e3
        return val

    # 2) 日期时间字符串：拆出整数秒与任意位数的小数秒
    m = re.match(
        r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?",
        raw,
    )
    if not m:
        return None
    year, mon, day, hh, mm, ss = (int(g) for g in m.groups()[:6])
    frac = m.group(7) or ""
    base = _dt.datetime(year, mon, day, hh, mm, ss, tzinfo=_dt.timezone.utc).timestamp()
    # 小数部分按位数归一（9 位 = 纳秒）
    return base + (float("0." + frac) if frac else 0.0)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# 输入适配
# --------------------------------------------------------------------------

def load_times_from_tsv(path: str):
    """读取 tshark 导出的 TSV（frame.time_epoch 列）。"""
    rows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for rec in csv.DictReader(fh, delimiter="\t"):
            raw = (rec.get("frame.time_epoch") or "").strip()
            if not raw:
                continue
            try:
                rows.append({"t": float(raw), "row": rec})
            except ValueError:
                continue
    return rows


def load_times_from_pcap(path: str):
    """用 tshark 现场解析 pcap。要求环境已安装 tshark。"""
    fields = [
        "frame.time_epoch", "ip.src", "ip.dst",
        "rtps.sm.id", "rtps.guidPrefix.src", "rtps.sm.wrEntityId", "rtps.domain_id",
    ]
    cmd = ["tshark", "-r", path, "-Y", "rtps", "-T", "fields",
           "-E", "header=y", "-E", "separator=/t", "-E", "occurrence=a"]
    for f in fields:
        cmd += ["-e", f]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=1800).stdout
    except FileNotFoundError:
        raise SystemExit("未找到 tshark，请先安装（见 scripts/data_provisioning/README.md）")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"tshark 解析失败：{exc.stderr[:400]}")
    rows = []
    for rec in csv.DictReader(out.splitlines(), delimiter="\t"):
        raw = (rec.get("frame.time_epoch") or "").strip()
        if not raw:
            continue
        try:
            rows.append({"t": float(raw), "row": rec})
        except ValueError:
            continue
    return rows


def load_times_from_labeled_csv(path: str, time_col: str | None = None,
                                resource_col: str | None = None,
                                resource_filter: str | None = None):
    """读取带时间列的 CSV（HCRL 标注 CSV、ROSPaCe 精简版等）。

    resource_col / resource_filter 用于按 ROS 2 话题名（如 ROSPaCe 的 ``src_topic``）
    只保留单个资源的样本，使统计口径对应到具体通信资源。
    """
    rows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(fh, dialect=dialect)
        if not reader.fieldnames:
            return rows, 0
        fields = reader.fieldnames

        cand = [time_col] if time_col else []
        cand += [c for c in fields
                 if c and re.search(r"(^|\b)(time|timestamp|epoch)", c.strip(), re.I)]
        col = next((c for c in cand if c and c in fields), None)
        if col is None:
            raise SystemExit(f"在 {path} 中找不到时间列，现有列：{fields[:12]}")

        if resource_filter and not resource_col:
            raise SystemExit("指定了 --resource-filter 时必须同时指定 --resource-col")
        if resource_col and resource_col not in fields:
            raise SystemExit(f"找不到资源列 {resource_col}，现有列：{fields[:12]}")

        skipped = 0
        for rec in reader:
            if resource_filter:
                actual = (rec.get(resource_col) or "").strip().strip('"')
                if actual != resource_filter:
                    skipped += 1
                    continue
            val = _parse_time(rec.get(col) or "")
            if val is None:
                skipped += 1
                continue
            rows.append({"t": val, "row": rec})
    return rows, skipped


# --------------------------------------------------------------------------
# 分析
# --------------------------------------------------------------------------

def analyze(rows, *, resource, resource_type, operation, baseline_hz,
            baseline_dispersion, dup_threshold, gap_sigma, evidence_kind,
            evidence_detail, producer_version):
    if not rows:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "UNKNOWN",
            "reason": "观察窗口内没有可解析的通信样本，证据不足。",
            "anomaly_category": "UNKNOWN",
            "risk_level": "UNKNOWN",
            "basis": ["样本数为 0，无法建立或比对基线。"],
            "_note": "UNKNOWN 表示证据不足，按契约不得解释为 NORMAL。",
        }

    times = sorted(r["t"] for r in rows)
    n = len(times)
    start, end = times[0], times[-1]
    duration_ms = max(0.0, (end - start) * 1000.0)

    # 契约：window.duration_ms 上界 24h
    if duration_ms > MAX_DURATION_MS:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "ERROR",
            "reason": f"观察窗口 {duration_ms:.0f} ms 超过契约上界 24 小时，拒绝输出失真结论。",
            "anomaly_category": "UNKNOWN",
            "risk_level": "UNKNOWN",
            "basis": [f"窗口长度 {duration_ms:.0f} ms > {MAX_DURATION_MS} ms。"],
        }

    freq = None
    if duration_ms > 0:
        freq = (n - 1) / (duration_ms / 1000.0)

    gaps = [times[i + 1] - times[i] for i in range(n - 1)]

    basis = [
        f"窗口内样本数 {n}，窗口长度 {duration_ms:.1f} ms。",
    ]
    category = "NONE"
    risk = "NONE"

    # 间隔统计：不做无依据的剔除，改用分位数如实描述分布形态。
    #
    # 设计说明（重要）：早期版本会"剔除疑似采集起停间隙"，但在真实 ROSPaCe 数据上
    # 该规则一次删掉了 1056 个间隔 —— 那是图像/日志话题本身固有的**成簇发送**特征，
    # 不是采集伪影。擅自丢弃真实观测会扭曲方差并掩盖真实流量形态，因此改为：
    #   * 如实报告中位数 / p95 / 最大值，且**不剔除任何观测**；
    #   * 抖动判据改用稳健口径 p95/中位数，对少量长间隔不敏感；
    #   * 所用口径全部写进 basis，可被复核。
    med_gap = p95_gap = max_gap = f_mean = f_std = None
    if gaps:
        srt = sorted(gaps)
        med_gap = srt[len(srt) // 2]
        p95_gap = srt[min(len(srt) - 1, int(0.95 * len(srt)))]
        max_gap = srt[-1]
        f_mean = sum(gaps) / len(gaps)
        if len(gaps) > 1:
            f_var = sum((g - f_mean) ** 2 for g in gaps) / (len(gaps) - 1)
            f_std = math.sqrt(f_var)
        basis.append(
            f"到达间隔：中位数 {med_gap*1000:.2f} ms，p95 {p95_gap*1000:.2f} ms，"
            f"最大 {max_gap*1000:.2f} ms（未剔除任何观测）。"
        )

    # 突发判定：若大多数样本挤在极短时间片内成簇到达，频率指标会失真，必须说明。
    burst = False
    if gaps and f_mean is not None:
        span_us = sum(gaps) * 1e6
        overall_us = duration_ms * 1000.0
        if f_mean < 1e-3 and overall_us > 0 and span_us < 0.05 * overall_us:
            burst = True
            basis.append(
                f"样本在约 {span_us:.0f} µs 内成簇到达，占整个窗口的 "
                f"{100.0*span_us/overall_us:.2f}%，判定为突发型流量；"
                f"{freq:.3f} Hz 只是窗口均值，不代表稳定速率，不得当作周期频率解读。"
            )

    # 判据 1：频率异常（需要基线）
    if baseline_hz and baseline_hz > 0 and freq is not None:
        ratio = freq / baseline_hz
        basis.append(
            f"观测频率 {freq:.3f} Hz，基线 {baseline_hz:.3f} Hz，比值 {ratio:.2f}×。"
        )
        if ratio >= 5.0:
            category, risk = "REQUEST_RATE_ANOMALY", "HIGH"
        elif ratio >= 2.0:
            category, risk = "REQUEST_RATE_ANOMALY", "MEDIUM"
        elif ratio <= 0.2:
            category, risk = "REQUEST_RATE_ANOMALY", "MEDIUM"
    else:
        basis.append("未提供基线频率：本工具不做频率正常性判断（避免无依据放行）。")

    # 判据 2：时间间隔抖动 —— 必须与**基线抖动**比较，不能只凭绝对形态判定。
    #
    # 设计说明（重要）：曾尝试用"p95/中位数 ≥ 阈值"作为无基线判据，但在真实 ROSPaCe
    # 数据上失败：图像与日志话题是成簇发送，中位间隔接近 0，导致 p95/中位数 高达 10^4，
    # 结果几乎所有话题都被判为 TIMING_DEVIATION —— 这是**误报**，不是异常。
    # 因此改为：只有提供了基线抖动时才对抖动做判断；否则只如实报告统计量。
    if category == "NONE" and med_gap is not None and p95_gap is not None and med_gap > 0:
        dispersion = p95_gap / med_gap
        if baseline_dispersion and baseline_dispersion > 0:
            ratio_d = dispersion / baseline_dispersion
            basis.append(
                f"抖动对比：本窗口 p95/中位数 = {dispersion:.2f}，"
                f"基线 {baseline_dispersion:.2f}，比值 {ratio_d:.2f}×（阈值 {gap_sigma}）。"
            )
            if ratio_d >= gap_sigma:
                category, risk = "TIMING_DEVIATION", "MEDIUM"
        else:
            basis.append(
                f"抖动统计：p95/中位数 = {dispersion:.2f}。"
                "**未提供基线抖动，故不对抖动做异常判定**——成簇发送会天然产生很大的该比值，"
                "单凭它下结论会产生大量误报。"
            )

    # 判据 3：重复调用模式（同内容**连续**重复）
    #
    # 设计说明（重要，两次真实数据修正的结论）：
    #   * 早期版本对"签名计数"取最大值，在**缺少 RTPS 标识列**的真实 ROSPaCe 数据上
    #     会把所有行折叠成同一个空签名而误报 → 改为先检查列是否存在；
    #   * 修正后又发现：仅凭"总计数"仍不可靠，因为即便有标识列，`frame.len` 之类字段
    #     本身取值很少，会把正常流量也算成"重复"。
    #   因此最终判据改为统计**连续相同**签名的最大游程（run length）：
    #   连续重复才是重放/重复调用的真实特征，偶发同长度不算。
    if category == "NONE":
        identity_cols = [k for k in ("rtps.sm.wrEntityId", "rtps.sm.seqNumber")
                         if any(k in r["row"] for r in rows[:50])]
        if not identity_cols:
            basis.append(
                "未做重复调用检测：本数据源不含 RTPS 身份标识列"
                "（writerEntityId / seqNumber），无法区分'重复调用'与'数据缺失'。"
            )
        else:
            best_run = 0
            cur_run = 0
            prev = object()
            for r in rows:
                key = tuple((r["row"].get(k) or "") for k in identity_cols)
                if key == prev:
                    cur_run += 1
                else:
                    cur_run = 1
                    prev = key
                best_run = max(best_run, cur_run)
            if best_run >= dup_threshold:
                category, risk = "DUPLICATE_CALL_PATTERN", "MEDIUM"
                basis.append(
                    f"检测到连续相同签名（{'/'.join(identity_cols)}）最长游程 {best_run}，"
                    f"达到阈值 {dup_threshold} —— 符合重复调用/重放特征。"
                )
            else:
                basis.append(
                    f"重复调用检测：连续相同签名（{'/'.join(identity_cols)}）"
                    f"最长游程 {best_run}，未达阈值 {dup_threshold}。"
                )

    status = "SUSPICIOUS" if category != "NONE" else "NORMAL"
    if category == "NONE" and not baseline_hz:
        # 没有任何基线可比时，不得声称 NORMAL
        status, category, risk = "UNKNOWN", "UNKNOWN", "UNKNOWN"
        basis.append("缺少基线且在本次窗口内未命中任何异常判据，证据不足以判定 NORMAL。")

    observed_at = _rfc3339(_dt.datetime.now(tz=_dt.timezone.utc).timestamp())
    run_id = "ds-" + hashlib.sha256(
        f"{resource}{start}{end}{n}".encode()).hexdigest()[:16]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "request_id": run_id,
        "event_id": run_id + "-e1",
        # 契约 producer 仅允许 name / module_version / source 三个键（additionalProperties: false）
        "producer": {
            "name": "dataset_commrisk_probe",
            "module_version": producer_version,
            "source": "EXTERNAL",
        },
        "observed_at": observed_at,
        "status": status,
        "reason": (
            f"在窗口 { _rfc3339(start) } ~ { _rfc3339(end) } 内观察到 {n} 个通信样本，"
            f"判定为 {category}。"
        ),
        "evidence_refs": [
            {
                "kind": evidence_kind,
                "ref": evidence_detail,
                "note": "标签/统计均由该数据源导出；未使用 Mock 数据。",
            }
        ],
        "communication": {
            "resource": resource,
            "resource_type": resource_type,
            "operation": operation,
        },
        "window": {
            "start": _rfc3339(start),
            "end": _rfc3339(end),
            "duration_ms": round(duration_ms, 3),
        },
        "request_count": n,
        "anomaly_category": category,
        "risk_level": risk,
        "basis": basis,
    }
    # 契约：frequency_hz 可选；无法计算时不得用 0 冒充
    if freq is not None and math.isfinite(freq):
        payload["frequency_hz"] = round(freq, 6)

    # 键顺序对齐 Schema 阅读顺序（非必需，便于人工比对）
    order = ["schema_version", "run_id", "request_id", "event_id", "producer",
             "observed_at", "status", "reason", "evidence_refs", "communication",
             "window", "request_count", "frequency_hz", "anomaly_category",
             "risk_level", "basis"]
    return {k: payload[k] for k in order if k in payload}


def validate_against_schema(doc: dict, schema_path: str) -> tuple[bool, str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return False, "未安装 jsonschema，跳过契约校验（不代表通过）"
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    try:
        jsonschema.validate(doc, schema)
    except Exception as exc:  # noqa: BLE001
        return False, f"契约校验失败：{exc}"
    return True, "契约校验通过"


def main(argv=None):
    ap = argparse.ArgumentParser(description="RTPS/PCAP → CommRiskEvidence 提取器")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pcap", help="RTPS pcap/pcapng 文件（需 tshark）")
    src.add_argument("--tsv", help="tshark 导出的 TSV（含 frame.time_epoch）")
    src.add_argument("--labeled-csv", help="HCRL 风格标注 CSV（含 Time 列）")
    ap.add_argument("--time-col", default=None, help="标注 CSV 的时间列名")
    ap.add_argument("--resource-col", default=None,
                    help="资源列名（如 ROSPaCe 的 src_topic），用于按话题过滤")
    ap.add_argument("--resource-filter", default=None,
                    help="只统计该资源值的样本；需配合 --resource-col")
    ap.add_argument("--resource", default="/unknown_dds_resource",
                    help="ROS 2 资源名；RTPS 数据无话题名时必须显式说明其局限")
    ap.add_argument("--resource-type", default="Topic", choices=RESOURCE_TYPES)
    ap.add_argument("--operation", default="PUBLISH", choices=OPERATIONS)
    ap.add_argument("--baseline-hz", type=float, default=None,
                    help="权威基线频率（来自 TaskPolicy 等），不提供则不做频率判定")
    ap.add_argument("--baseline-p95-ratio", type=float, default=None,
                    help="基线窗口的 p95/中位数 抖动值；提供后才对抖动做异常判定")
    ap.add_argument("--dup-threshold", type=int, default=50)
    ap.add_argument("--gap-cv", type=float, default=2.0, help="间隔变异系数阈值")
    ap.add_argument("--evidence-kind", default="CONTROLLED_SECURITY_EXPERIMENT",
                    choices=("RUNTIME_LOG", "PERMISSION_FILE_ANALYSIS",
                             "CONTROLLED_SECURITY_EXPERIMENT", "MOCK", "UNKNOWN"))
    ap.add_argument("--evidence-detail", default="")
    ap.add_argument("--producer-version", default="0.1.0")
    ap.add_argument("--schema", default=None, help="用于校验的 CommRiskEvidence Schema 路径")
    ap.add_argument("--out", default=None, help="输出 JSON 路径；默认 stdout")
    args = ap.parse_args(argv)

    if args.pcap:
        rows = load_times_from_pcap(args.pcap)
        detail = args.evidence_detail or f"pcap={os.path.basename(args.pcap)} sha256={_sha256_file(args.pcap)[:16]}…"
    elif args.tsv:
        rows = load_times_from_tsv(args.tsv)
        detail = args.evidence_detail or f"tsv={os.path.basename(args.tsv)} sha256={_sha256_file(args.tsv)[:16]}…"
    else:
        rows, skipped = load_times_from_labeled_csv(
            args.labeled_csv, args.time_col, args.resource_col, args.resource_filter)
        scope = f" resource={args.resource_filter}" if args.resource_filter else ""
        detail = args.evidence_detail or (
            f"labeled-csv={os.path.basename(args.labeled_csv)}{scope}")
        if skipped:
            print(f"提示：{skipped} 行未纳入统计"
                  f"（资源不匹配或时间无法解析）。", file=sys.stderr)

    if args.resource == "/unknown_dds_resource":
        print("警告：未指定 --resource。RTPS 抓包不含 ROS 2 话题名，"
              "communication.resource 只能占位，不得据此声称已识别具体业务资源。",
              file=sys.stderr)

    doc = analyze(
        rows,
        resource=args.resource,
        resource_type=args.resource_type,
        operation=args.operation,
        baseline_hz=args.baseline_hz,
        baseline_dispersion=args.baseline_p95_ratio,
        dup_threshold=args.dup_threshold,
        gap_sigma=args.gap_cv,
        evidence_kind=args.evidence_kind,
        evidence_detail=detail,
        producer_version=args.producer_version,
    )

    if args.schema:
        ok, msg = validate_against_schema(doc, args.schema)
        print(("[契约校验] " + msg), file=sys.stderr)
        if not ok:
            return 2

    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"已写出 {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
