import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import continuous_runner


class StartupComplete(Exception):
    pass


class TasNewTests(unittest.TestCase):
    def test_old_run_cannot_seed_new_run(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory)/'lua.log'
            old = ('AUTOMATION_READY=AAAA/AAAA/AAAA/AAAA\n'
                   'AUTOMATION_DIALOG=treasure|1|E\nno more enemies left\n')
            log.write_text(old + 'Book:StartGame called for book 1, chapter 1\n')
            self.assertEqual(continuous_runner.read_seed(log, len(old)), (None, False, False, 1))
            self.assertIsNone(continuous_runner.read_latest_dialog(log, len(old)))

    def test_truncated_log_restarts_at_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory)/'lua.log'
            log.write_text('new log')
            self.assertEqual(continuous_runner.read_log_tail(log, 1000), 'new log')

    def test_preload_and_lock_precede_profile_confirmation(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            argv = ['continuous_runner', '--layout', 'deluxe', '--log', str(root/'lua.log'),
                    '--timer-state', str(root/'timer.json'), '--new-run', '--profile', 'Lex10']
            stack.enter_context(patch('sys.argv', argv))
            stack.enter_context(patch.object(continuous_runner, 'configure_logging'))
            stack.enter_context(patch.object(continuous_runner, 'acquire_runner_lock',
                                            side_effect=lambda *_: calls.append('lock') or Mock()))
            stack.enter_context(patch.object(continuous_runner, 'index_words',
                                            side_effect=lambda *_: calls.append('dictionary') or []))
            stack.enter_context(patch.object(continuous_runner, 'load_metal_words', return_value=frozenset()))
            stack.enter_context(patch.object(continuous_runner, 'load_chapter1_hp_map', return_value={}))
            stack.enter_context(patch.object(continuous_runner.TransitionCorpus, 'load',
                                            side_effect=lambda *_: calls.append('corpus') or Mock()))
            stack.enter_context(patch.object(continuous_runner.DecisionOverrides, 'load',
                                            side_effect=lambda *_: calls.append('overrides') or Mock()))
            stack.enter_context(patch.object(continuous_runner, 'X11Keyboard', return_value=Mock()))

            def recreate(_controller, name, **kwargs):
                self.assertEqual(calls, ['lock', 'dictionary', 'corpus', 'overrides'])
                self.assertEqual(name, 'Lex10')
                self.assertFalse(kwargs['startup_bridge'])
                self.assertEqual(kwargs['timer_path'], root/'timer.json')
                calls.append('recreate')
                return 123

            stack.enter_context(patch('new_run.recreate_profile', side_effect=recreate))

            def seed(path, offset):
                self.assertEqual(calls[-1], 'recreate')
                self.assertEqual(offset, 123)
                raise StartupComplete()

            stack.enter_context(patch.object(continuous_runner, 'read_seed', side_effect=seed))
            with self.assertRaises(StartupComplete):
                continuous_runner.main()

    def test_new_run_rejects_web_layout_before_input(self):
        with patch('sys.argv', ['runner', '--log', 'unused', '--new-run']), \
                patch.object(continuous_runner, 'X11Keyboard') as controller:
            with self.assertRaises(SystemExit):
                continuous_runner.main()
            controller.assert_not_called()
