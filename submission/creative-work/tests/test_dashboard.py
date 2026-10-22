"""控制台自检：验证"只读证据 + 白名单运行 + 不伪造结果"。

这些测试不需要 ROS 2，也不需要 docker。
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'dashboard'))

import evidence_loader as ev          # noqa: E402
from run_controller import ALLOWED_MODES, RUN_ID_RE, RunController  # noqa: E402


class EvidenceTest(unittest.TestCase):
    def test_replay_manifest_is_real_evidence(self):
        r = ev.load_replay()
        self.assertIsInstance(r, dict)
        self.assertEqual(r['contract'], 'rosystem-replay-snapshot/1')
        # 必须来自真实归档，且标注不代表本次在线执行
        self.assertIn('REPLAY', r['replay_notice'])
        self.assertIn('timeout_is_not_block', r['semantics'])

    def test_replay_numbers_match_archived_evidence(self):
        r = ev.load_replay()
        self.assertEqual(r['m3']['checks'], 36)
        self.assertEqual(r['m3']['failures'], 0)
        self.assertTrue(r['m3']['claims_checked'])
        self.assertEqual(r['dds_enforce']['passed'], 7)
        self.assertEqual(r['dds_enforce']['total'], 7)

    def test_timeout_comparison_has_two_runs_and_no_ordering_claim(self):
        r = ev.load_replay()
        self.assertEqual(len(r['timeout_comparison']), 2)
        self.assertTrue(r['semantics']['ordering_not_claimed'])

    def test_loader_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            ev._safe_join('/tmp/base', '..', '..', 'etc', 'passwd')

    def test_missing_run_returns_none_not_fake(self):
        self.assertIsNone(ev.load_run('artifacts/does-not-exist'))


class ResearchEvidenceTest(unittest.TestCase):
    def test_research_snapshot_is_archived_not_online(self):
        r = ev.load_research_evidence()
        self.assertIsInstance(r, dict)
        self.assertEqual(r['contract'], 'rosystem-research-evidence/1')
        self.assertEqual(r['evidence_class'], 'ARCHIVED_RESEARCH_EVIDENCE')
        self.assertFalse(r['online_evidence'])
        ids = {i['id']: i for i in r['items']}
        self.assertEqual(ids['DDS_ENFORCE']['value'], '7/7')
        self.assertEqual(ids['DDS_NEGATIVE']['value'], '6/6')
        self.assertEqual(ids['M2_IDENTITY']['value'], '17/17')
        self.assertEqual(ids['GATEWAY']['value'], '14/14')
        self.assertEqual(ids['P07']['value'], '13/13')
        self.assertEqual(ids['P09']['value'], '10/10')
        self.assertEqual(ids['THREE_REAL_L3']['status'], 'BLOCKED')
        self.assertEqual(ids['ACTION_BINDING']['status'], 'NOT_VERIFIED')
        self.assertEqual(r['acceptance']['status'], 'INCOMPLETE')
        self.assertIn('THREE_REAL_LEVEL3', r['acceptance']['not_run'])
        self.assertIn('不是本次在线运行', r['notice'])

    def test_research_snapshot_cannot_be_mistaken_for_online(self):
        r = ev.load_research_evidence()
        self.assertNotEqual(r.get('evidence_class'), 'ONLINE_EVIDENCE')
        self.assertNotEqual(r.get('evidence_class'), 'REPLAY')


class RunControllerTest(unittest.TestCase):
    def test_whitelist_only(self):
        self.assertEqual(set(ALLOWED_MODES),
                         {'controlled', 'three-real-strict', 'enforce',
                          'acceptance', 'check'})

    def test_unknown_mode_rejected(self):
        c = RunController()
        with unittest.mock.patch.object(c, 'busy', return_value=False):
            r = c.start('rm -rf /')
        self.assertFalse(r['ok'])
        self.assertIn('不允许的模式', r['error'])

    def test_run_id_validation(self):
        self.assertTrue(RUN_ID_RE.match('ok-1'))
        self.assertFalse(RUN_ID_RE.match('../etc'))
        self.assertFalse(RUN_ID_RE.match('a' * 65))

    def test_bad_run_id_rejected(self):
        c = RunController()
        with unittest.mock.patch.object(c, 'busy', return_value=False):
            r = c.start('controlled', '../evil')
        self.assertFalse(r['ok'])


import unittest.mock  # noqa: E402  (用于 patch)


class SecurityP0Test(unittest.TestCase):
    """P0-4：证据路径封闭、run_id 边界、并发原子化、POST 防护。"""

    def test_absolute_path_rejected(self):
        with self.assertRaises(ev.UnsafePath):
            ev.resolve_evidence_dir('/etc')

    def test_dotdot_rejected(self):
        for bad in ('../etc', 'a/../../etc', './x', 'a/./b'):
            with self.assertRaises(ev.UnsafePath):
                ev.resolve_evidence_dir(bad)

    def test_outside_root_rejected(self):
        with self.assertRaises(ev.UnsafePath):
            ev.resolve_evidence_dir('submission/creative-work')

    def test_symlink_escape_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = ev._allowed_roots()
            if not root:
                self.skipTest('无可用证据根')
            link = os.path.join(root[0], 'escape-link')
            try:
                os.symlink('/etc', link)
            except OSError:
                self.skipTest('无法创建符号链接')
            try:
                with self.assertRaises(ev.UnsafePath):
                    ev.resolve_evidence_dir(
                        os.path.relpath(link, ev.REPO_ROOT))
            finally:
                os.unlink(link)

    def test_run_id_boundaries(self):
        from run_controller import validate_run_id
        for bad in ('.', '..', '../etc', 'a/b', 'a\\b', '', 'a' * 65, ' lead'):
            ok, _why = validate_run_id(bad)
            self.assertFalse(ok, '应拒绝 %r' % bad)
        for good in ('ok-1', 'dash-20261021T000000Z', 'a.b_c-1'):
            ok, why = validate_run_id(good)
            self.assertTrue(ok, '应接受 %r：%s' % (good, why))

    def test_concurrent_start_is_atomic(self):
        """两个并发启动只能成功一个。"""
        import threading
        import unittest.mock as mock
        from run_controller import RunController
        c = RunController()
        results = []
        barrier = threading.Barrier(2)

        def attempt(i):
            barrier.wait()
            with mock.patch('subprocess.Popen') as popen:
                popen.return_value.pid = 1000 + i
                popen.return_value.wait.return_value = 0
                results.append(c.start('controlled', 'conc-%d' % i))

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sum(1 for r in results if r.get('ok')), 1,
                         '并发启动必须只有一个成功')

    def test_replay_view_is_unified(self):
        """P0-1：/api/replay 的统一视图模型必须自带 m3 / timeout_comparison。"""
        import importlib
        import server as srv
        view = srv.build_replay_view()
        self.assertIsNotNone(view)
        self.assertEqual(view['mode'], 'REPLAY')
        self.assertIn('m3', view)
        self.assertEqual(view['m3']['checks'], 36)
        self.assertEqual(len(view['timeout_comparison']), 2)
        self.assertIsNotNone(view['tested_code_sha'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
