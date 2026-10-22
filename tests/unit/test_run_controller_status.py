"""run_controller 的退出码 -> 状态映射测试（1.0.3）。

控制台必须把 exit 9（NOT_RUN / INCOMPLETE）显示为 INCOMPLETE，
既不能当 DONE（会误导为通过），也不能当普通 FAIL（会掩盖"没跑完"）。
"""
import importlib.util
import io
import os
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Repo layout: <repo>/submission/creative-work/dashboard.
# Full package layout: <package>/runtime is REPO and <package>/dashboard is a sibling.
_CANDIDATES = (
    os.path.join(REPO, 'submission', 'creative-work', 'dashboard', 'run_controller.py'),
    os.path.join(os.path.dirname(REPO), 'dashboard', 'run_controller.py'),
)
MODULE = next((p for p in _CANDIDATES if os.path.isfile(p)), _CANDIDATES[0])

spec = importlib.util.spec_from_file_location('run_controller', MODULE)
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


class FakeProc(object):
    def __init__(self, code):
        self.returncode = code
        self.pid = 424242

    def wait(self, timeout=None):
        return self.returncode


def _drive(code):
    ctrl = rc.RunController()
    fh = tempfile.TemporaryFile(mode='w+')
    ctrl._wait(FakeProc(code), fh)
    return ctrl.status()


def test_zero_is_done():
    assert _drive(0)['status'] == 'DONE'


def test_nine_is_incomplete_not_done():
    st = _drive(9)
    assert st['status'] == 'INCOMPLETE'      # 不是 DONE
    assert st['status'] != 'DONE'
    assert st['exit_code'] == 9
    assert '未执行' in (st['error'] or '') or '不完整' in (st['error'] or '')


def test_one_is_fail():
    st = _drive(1)
    assert st['status'] == 'FAIL'
    assert st['exit_code'] == 1


def test_four_is_fail():
    assert _drive(4)['status'] == 'FAIL'
