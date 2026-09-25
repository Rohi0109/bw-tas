import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from continuous_runner import main, telemetry_context
from experiment_session import create_session
from test_deluxe_optimizer import state


class ExperimentTests(unittest.TestCase):
    def test_sessions_have_distinct_ids_and_actual_build_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'BookwormAdventures.exe').write_bytes(b'exe')
            (path/'main.pak').write_bytes(b'pak')
            a, b = create_session(path), create_session(path)
            self.assertNotEqual(a, b)
            record = json.loads((path/'sessions'/f'{a}.json').read_text())
            self.assertEqual(record['file_hashes']['main.pak'],
                             hashlib.sha256(b'pak').hexdigest())
            self.assertFalse(record['rng_state_captured'])

    def test_chapter_recovers_without_timer(self):
        self.assertEqual(telemetry_context(state(chapter=-1, enemy='Scylla'), None), (1, 3))
        self.assertEqual(telemetry_context(state(chapter=-1, enemy='Circe (Boss)'), None), (1, 4))
        self.assertEqual(telemetry_context(state(chapter=-1, enemy='unknown'), None), (1, -1))

    def test_experiment_rejects_normal_profile_reset_before_input(self):
        with patch('sys.argv', ['runner', '--log', 'test.log', '--layout', 'deluxe',
                                '--experiment', '--new-run']), \
                patch('continuous_runner.X11Keyboard') as controller:
            with self.assertRaises(SystemExit) as stopped:
                main()
            self.assertEqual(stopped.exception.code, 2)
            controller.assert_not_called()
