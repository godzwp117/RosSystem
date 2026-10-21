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


if __name__ == '__main__':
    unittest.main(verbosity=2)
