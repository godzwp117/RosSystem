#!/usr/bin/env python3
"""Lightweight consistency gate for the 1.1.1-rc1 paper facts.

This script does not rewrite numbers. It fails when a document makes a claim that
contradicts the frozen baseline, the final package manifest, or the recorded
evidence limitations.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / 'paper'
FINAL_SHA = 'd69737cf9dbd039a4a0b8a127eb15bb3db55b5514512c119befd46d5e0fe32d2'
OFFLINE_SHA = '2fa7892deee52c079a76b51064acf7357f7b4bd7d655b3ab04d5081efa00a2b9'
FINAL_COMMIT = '40fded595afceced4205d2fae9756d6c90f95617'

errors: list[str] = []
checks: list[str] = []


def ok(name: str) -> None:
    checks.append(name)


def fail(name: str, detail: str) -> None:
    errors.append(f'{name}: {detail}')


def text(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        fail('missing-file', rel)
        return ''
    return path.read_text(encoding='utf-8', errors='replace')


def require(rel: str, *needles: str) -> None:
    body = text(rel)
    for needle in needles:
        if needle not in body:
            fail('missing-text', f'{rel} 缺少 {needle!r}')
    if all(n in body for n in needles):
        ok(f'{rel}: required text present')


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# 1) package identity
full = ROOT / 'submission/creative-work/dist/RosSystem-CreativeWork-Full-1.1.1-rc1.tar.gz'
offline = ROOT / 'submission/creative-work/dist/RosSystem-creative-work-1.1.1-rc1.tar.gz'
if full.is_file() and sha256(full) == FINAL_SHA:
    ok('final full package SHA-256 matches manifest')
else:
    fail('package-sha', f'{full} 不存在或 SHA-256 不是 {FINAL_SHA}')
if offline.is_file() and sha256(offline) == OFFLINE_SHA:
    ok('offline package SHA-256 matches manifest')
else:
    fail('offline-sha', f'{offline} 不存在或 SHA-256 不是 {OFFLINE_SHA}')

# 2) frozen baseline remains historical 920/4 and immutable
base = json.loads(text('paper/PAPER_FACTS_BASELINE.json') or '{}')
if base.get('immutable') is True:
    ok('baseline is immutable')
else:
    fail('baseline-immutable', 'PAPER_FACTS_BASELINE.json 的 immutable 不是 true')
base_text = text('paper/PAPER_FACTS_BASELINE.md')
if '920 passed' in base_text and '4 skipped' in base_text:
    ok('baseline still records 920/4')
else:
    fail('baseline-920', 'PAPER_FACTS_BASELINE.md 不再保留 920/4')

# 3) final facts block
require('paper/PAPER_FACTS_FINAL.md',
        'FINAL_CANDIDATE                 = 1.1.1-rc1',
        'FINAL_ACCEPTANCE_SOURCE_COMMIT  = ' + FINAL_COMMIT,
        'FINAL_FULL_SHA256               = ' + FINAL_SHA,
        'FINAL_UNIT_TESTS                = 921 passed / 17 skipped / 0 failed / 603.8 s',
        'HISTORICAL_BASELINE',
        'FINAL_PACKAGE_VALIDATION',
        'THREE_REAL_LEVEL3', 'BLOCKED',
        'Action `send_goal` 身份', 'NOT_VERIFIED',
        '第三方主机复现', 'NOT_RUN',
        'P07', 'CONTROLLED_ISOLATION',
        'ARCHIVED_RESEARCH_EVIDENCE',
        'TEST_ONLY_LAB')

# 4) statistics wording: tests are not independent experiments
require('paper/STATISTICAL_ANALYSIS.md', '921 passed', '17 skipped',
        '不是 921 次独立系统实验', 'skipped', '不进入')

# 5) CSV rows
rows = list(csv.DictReader(text('paper/EXPERIMENT_RESULTS.csv').splitlines()))
by_id = {r['experiment_id']: r for r in rows}
e18 = by_id.get('E18', {})
e20 = by_id.get('E20', {})
if e18.get('version') == '1.1.0' and '920' in e18.get('actual', ''):
    ok('E18 is historical/source 1.1.0, not final package')
else:
    fail('csv-E18', 'E18 必须标为 1.1.0 源码/历史基线')
if e20.get('version') == '1.1.1-rc1' and '921 passed / 17 skipped / 0 failed' in e20.get('actual', '') and 'NOT_RECOVERED' in e20.get('limitation', ''):
    ok('E20 records final package 921/17/0 and log limitation')
else:
    fail('csv-E20', 'E20 必须记录 921/17/0 和原始日志未恢复')

# 6) recovery status and skip audit exist
require('paper/UNIT_TEST_LOG_RECOVERY_STATUS.md',
        'ORIGINAL_FULL_PYTEST_LOG = NOT_RECOVERED',
        'HISTORICAL_RESULT     = 921 passed / 17 skipped / 0 failed',
        'HISTORICAL_DURATION   = 603.8 seconds')
require('paper/FINAL_PACKAGE_REPRODUCTION.md', FINAL_SHA, '603.8', 'NOT_RECOVERED')
require('paper/FINAL_UNIT_TEST_EVIDENCE_AUDIT.md',
        'FINAL_PACKAGE_TEST_RESULT_RECORDED = PASS',
        'ORIGINAL_PYTEST_LOG_ARCHIVED       = NOT_RECOVERED',
        'ALL_17_SKIP_REASONS_IDENTIFIED     = PASS',
        'SECURITY_SKIP_IMPACT_AUDITED       = PASS')

# 6b) claim matrix current rows for P07/P09/acceptance
claim_text = text('paper/CLAIM_EVIDENCE_MATRIX.csv')
for needle in ('C11,P07 M3 建议阻断 → F0 阻断（隔离）,PASS',
               'C12,P09 Planner TIMEOUT 语义,PASS',
               '4 项 NOT_RUN'):
    if needle not in claim_text:
        fail('claim-matrix', f'缺少 {needle!r}')
if 'C11,P07 M3 建议阻断 → F0 阻断（隔离）,PASS' in claim_text:
    ok('claim matrix P07/P09/acceptance rows are current')

# 7) final maturity/security boundaries
report = text('submission/creative-work/reports/ROSYSTEM_SIX_HOUR_RESEARCH_OPTIMIZATION_REPORT.md')
for needle in ('FINAL_MATURITY                  = LEVEL_C',
               'THREE_REAL_LEVEL3               = BLOCKED',
               'M2_ACTION_SEND_GOAL_BINDING     = NOT_VERIFIED',
               'THIRD_PARTY_HOST_REPRODUCED     = NOT_RUN',
               'WEB_RESEARCH_EVIDENCE           = PASS'):
    if needle not in report:
        fail('report-matrix', f'缺少 {needle!r}')
if 'FINAL_MATURITY                  = LEVEL_C' in report:
    ok('report keeps LEVEL C and blocked/not-verified boundaries')

# 8) forbidden mis-statements in the final-facing documents
for rel in ('paper/PAPER_FACTS_FINAL.md', 'paper/STATISTICAL_ANALYSIS.md',
            'paper/FINAL_PACKAGE_REPRODUCTION.md',
            'submission/creative-work/reports/ROSYSTEM_SIX_HOUR_RESEARCH_OPTIMIZATION_REPORT.md'):
    body = text(rel)
    for bad in ('921 次独立系统实验', '921 次独立实验'):
        if bad in body:
            # Only allowed in an explicit negation sentence.
            for m in re.finditer(re.escape(bad), body):
                start = max(0, m.start() - 20)
                prefix = body[start:m.start()]
                if '不是' not in prefix and '不得' not in prefix:
                    fail('misstatement', f'{rel}: {bad!r} 未被否定')
                    break
    if 'skipped 计入 passed' in body or 'skipped 计为 PASS' in body:
        fail('misstatement', f'{rel}: 把 skipped 计入 passed/PASS')
ok('forbidden-misstatement scan completed')

# 9) skip CSV, when present, must not invent nodeids / must mark source
skip_csv = PAPER / 'FINAL_PACKAGE_SKIPPED_TESTS.csv'
if skip_csv.is_file():
    srows = list(csv.DictReader(skip_csv.read_text(encoding='utf-8').splitlines()))
    allowed = {'ORIGINAL_PYTEST_LOG', 'SOURCE_CODE_ANALYSIS', 'UNKNOWN'}
    bad_sources = sorted({r.get('reason_source') for r in srows} - allowed)
    if bad_sources:
        fail('skip-source', f'非法 reason_source: {bad_sources}')
    if len(srows) not in (0, 17) and 'RECONCILIATION' not in skip_csv.read_text(encoding='utf-8'):
        fail('skip-count', f'CSV 行数 {len(srows)} 不是 17，且未声明对账差异')
    ok(f'skip CSV present ({len(srows)} rows)')

print('== paper fact consistency ==')
for name in checks:
    print('PASS', name)
for err in errors:
    print('FAIL', err)
print(f'RESULT: {"PASS" if not errors else "FAIL"} ({len(checks)} checks, {len(errors)} errors)')
sys.exit(0 if not errors else 1)
