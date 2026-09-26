import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from local_watchdog import diagnose, restart_allowed, supervise


class LocalWatchdogTests(unittest.TestCase):
    def test_real_crashed_child_restarts_then_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root/'child.py'
            script.write_text("from pathlib import Path\n"
                              "p=Path('count')\n"
                              "n=int(p.read_text()) if p.exists() else 0\n"
                              "p.write_text(str(n+1))\n"
                              "raise SystemExit(7 if n==0 else 0)\n")
            with patch('local_watchdog.diagnose', return_value=dict(status='failed')), \
                    patch('local_watchdog.time.sleep'):
                code = supervise(command=[sys.executable, str(script)], repo=root,
                                 log=root/'lua.log', incidents=root/'incidents',
                                 model='test', max_restarts=1, stall_seconds=5,
                                 timeout_seconds=10, cooldown_seconds=1)
            self.assertEqual(code, 0)
            self.assertEqual((root/'count').read_text(), '2')

    def test_policy_bounds_and_timeout(self):
        stall = dict(reason='lua log unchanged for 20 seconds')
        self.assertTrue(restart_allowed(124, stall, 0, 1))
        self.assertFalse(restart_allowed(124, stall, 1, 1))
        self.assertFalse(restart_allowed(124, dict(reason='process timeout after 60 seconds'), 0, 1))
        self.assertFalse(restart_allowed(-15, dict(reason='runner exited with code -15'), 0, 1))

    def test_model_unavailable_is_recorded(self):
        with patch('local_watchdog.run', side_effect=OSError('offline')):
            self.assertEqual(diagnose({}, 'test')['status'], 'failed')

    def test_restart_limit_applies_across_different_incidents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packets = []
            for n in range(2):
                path = root / f'incident{n}.json'
                path.write_text(json.dumps(dict(reason='lua log unchanged for 20 seconds', signature=str(n))))
                packets.append(path)
            with patch('local_watchdog.run_watchdog', side_effect=[(124, p) for p in packets]) as monitor, \
                    patch('local_watchdog.diagnose', return_value=dict(status='invalid')), \
                    patch('local_watchdog.time.sleep'):
                code = supervise(command=['test'], repo=root, log=root/'lua.log',
                                 incidents=root/'incidents', model='test', max_restarts=1,
                                 stall_seconds=20, timeout_seconds=None, cooldown_seconds=5)
            self.assertEqual(code, 124)
            self.assertEqual(monitor.call_count, 2)
            reports = [json.loads(p.with_suffix('.local-diagnosis.json').read_text()) for p in packets]
            self.assertTrue(reports[0]['recovery']['restart_runner'])
            self.assertFalse(reports[1]['recovery']['restart_runner'])


if __name__ == '__main__':
    unittest.main()
