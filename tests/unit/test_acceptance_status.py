"""acceptance_status 的状态语义回归测试（1.0.3）。

覆盖任务书 5.1–5.4：
  5.1 全部 PASS              -> ACCEPTANCE=PASS, exit 0
  5.2 存在 NOT_RUN           -> ACCEPTANCE=INCOMPLETE, 非零退出
  5.3 存在 FAIL              -> ACCEPTANCE=FAIL
  5.4 FAIL 与 NOT_RUN 并存   -> FAIL（且保留 NOT_RUN 记录）

这些测试只验证"状态聚合语义"，不声称任何真实实验已执行。
"""
import importlib.util
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULE = os.path.join(REPO, 'scripts', 'acceptance_status.py')

spec = importlib.util.spec_from_file_location('acceptance_status', MODULE)
acc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acc)

ALL_ITEMS = ('HOST_TESTS', 'THREE_REAL', 'CONTROLLED', 'M3_SIX', 'ENFORCE')


def items(**overrides):
    base = {name: acc.PASS for name in ALL_ITEMS}
    base.update(overrides)
    return base


# ---------------------------------------------------------------- 5.1
def test_all_pass_is_pass():
    status, code, not_run, failed = acc.aggregate(items())
    assert (status, code, not_run, failed) == (acc.PASS, 0, [], [])


# ---------------------------------------------------------------- 5.2
def test_enforce_not_run_is_incomplete_not_pass():
    status, code, not_run, failed = acc.aggregate(items(ENFORCE=acc.NOT_RUN))
    assert status == acc.INCOMPLETE
    assert code == 9          # 关键：不得返回 0
    assert code != 0
    assert not_run == ['ENFORCE']
    assert failed == []


def test_not_run_never_returns_zero():
    for name in ALL_ITEMS:
        status, code, _, _ = acc.aggregate(items(**{name: acc.NOT_RUN}))
        assert status == acc.INCOMPLETE
        assert code == 9


# ---------------------------------------------------------------- 5.3
def test_any_fail_is_fail():
    status, code, not_run, failed = acc.aggregate(items(CONTROLLED=acc.FAIL))
    assert status == acc.FAIL
    assert code == 1
    assert failed == ['CONTROLLED']


# ---------------------------------------------------------------- 5.4
def test_fail_and_not_run_is_fail_and_keeps_not_run():
    status, code, not_run, failed = acc.aggregate(
        items(THREE_REAL=acc.FAIL, ENFORCE=acc.NOT_RUN))
    assert status == acc.FAIL          # 不得用 INCOMPLETE 掩盖 FAIL
    assert code == 1
    assert failed == ['THREE_REAL']
    assert not_run == ['ENFORCE']      # NOT_RUN 记录必须保留


# ---------------------------------------------------------------- 边界
def test_empty_is_not_pass():
    status, code, _, _ = acc.aggregate({})
    assert status == acc.INCOMPLETE
    assert code == 9


def test_unknown_status_rejected():
    try:
        acc.parse_items(['X=MAYBE'])
    except ValueError as exc:
        assert 'MAYBE' in str(exc)
    else:
        raise AssertionError('未知状态必须被拒绝')


def test_duplicate_item_rejected():
    try:
        acc.parse_items(['X=PASS', 'X=FAIL'])
    except ValueError as exc:
        assert '重复' in str(exc)
    else:
        raise AssertionError('重复项目必须被拒绝')


def test_malformed_item_rejected():
    try:
        acc.parse_items(['NOEQUALS'])
    except ValueError:
        pass
    else:
        raise AssertionError('缺等号必须被拒绝')


# ---------------------------------------------------------------- CLI 契约
def _run(args):
    return subprocess.run([sys.executable, MODULE] + args,
                          capture_output=True, text=True)


def test_cli_line_and_exit_incomplete():
    proc = _run(['HOST_TESTS=PASS', 'THREE_REAL=PASS', 'CONTROLLED=PASS',
                 'M3_SIX=PASS', 'ENFORCE=NOT_RUN'])
    assert proc.returncode == 9
    assert proc.stdout.strip() == 'INCOMPLETE 9 ENFORCE -'


def test_cli_exit_pass():
    proc = _run(['HOST_TESTS=PASS', 'ENFORCE=PASS'])
    assert proc.returncode == 0
    assert proc.stdout.strip() == 'PASS 0 - -'


def test_cli_exit_fail():
    proc = _run(['HOST_TESTS=FAIL', 'ENFORCE=NOT_RUN'])
    assert proc.returncode == 1
    assert proc.stdout.split()[0] == 'FAIL'


def test_cli_json_mode():
    proc = _run(['--json', 'ENFORCE=NOT_RUN'])
    assert proc.returncode == 9
    doc = json.loads(proc.stdout)
    assert doc['acceptance'] == 'INCOMPLETE'
    assert doc['exit_code'] == 9
    assert doc['not_run'] == ['ENFORCE']


def test_cli_bad_status_exit_2():
    proc = _run(['X=NOPE'])
    assert proc.returncode == 2
