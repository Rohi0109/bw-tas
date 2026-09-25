import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from menu_trace import MenuTrace
from menu_runner import reset_from_battle, MenuTiming


class MenuTraceTests(unittest.TestCase):
    def test_report_distinguishes_map_from_start_game_and_reports_missing_map(self):
        from menu_trace_report import summarize
        result = summarize([
            dict(cycle_id='a', stage='reset_requested', elapsed=0),
            dict(cycle_id='a', stage='chapter_map_observed', elapsed=1.8),
            dict(cycle_id='a', stage='chapter_callback_observed', action='start-game', elapsed=2.2),
            dict(cycle_id='a', stage='battle_ready_observed', elapsed=3.1),
            dict(cycle_id='a', stage='attack_requested', elapsed=3.2),
            dict(cycle_id='b', stage='reset_requested', elapsed=0),
            dict(cycle_id='b', stage='chapter_callback_observed', action='start-game', elapsed=2.8),
        ])
        self.assertEqual(result['phase_seconds']['reset_to_map']['count'], 1)
        self.assertEqual(result['phase_seconds']['reset_to_map']['median'], 1.8)
        self.assertAlmostEqual(result['phase_seconds']['start_game_to_ready']['median'], .9)
        self.assertEqual(result['cycles_without_observation']['chapter_map_observed'], 1)

    def test_presentation_skip_completes_only_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'reset.jsonl'
            trace = MenuTrace(path)
            trace.begin()
            for message in ('Attack 1: ABC -> CAB',
                            'Attack timing CAB: submitted during presentation skip; final_tile_to_ack_ms=20',
                            'Attack timing CAB: submitted_ack; enter_to_ack_ms=20'):
                trace.emit(logging.LogRecord('test', logging.DEBUG, '', 0, message, (), None))
            trace.close()
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(sum(r.get('status') == 'complete' for r in rows), 1)

    def test_cycle_only_completes_on_ack_and_ignores_old_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'reset.jsonl'
            trace = MenuTrace(path, 'test', clock=lambda: 10)
            def log(message):
                trace.emit(logging.LogRecord('test', logging.DEBUG, '', 0, message, (), None))
            log('Attack timing OLD: submitted_ack;')
            self.assertFalse(path.exists())
            log('State 12: Enemy HP 4/4')
            trace.begin()
            log('Attack timing OLD: submitted_ack;')
            self.assertIsNotNone(trace.cycle)
            log('Attack 1: ABCD -> BAD')
            self.assertIsNotNone(trace.cycle)
            log('Attack timing BAD: submitted_ack;')
            self.assertIsNone(trace.cycle)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r['stage'] for r in rows],
                             ['reset_requested', 'attack_requested', 'attack_acknowledged'])
            self.assertIn('State 12', rows[0]['context']['state'])
            self.assertEqual(len({r['cycle_id'] for r in rows}), 1)
            trace.close()

    def test_report_excludes_incomplete_cycles(self):
        from menu_trace_report import summarize
        result = summarize([
            dict(cycle_id='a', stage='attack_acknowledged', elapsed=4, status='complete'),
            dict(cycle_id='b', stage='dialog_ack_timeout', elapsed=.7),
        ])
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['incomplete'], 1)
        self.assertEqual(result['dialog_timeouts'], 1)
        self.assertEqual(result['seconds_since_reset_request']['attack_acknowledged']['median'], 4)

    def test_superseded_cycle_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'reset.jsonl'
            trace = MenuTrace(path)
            trace.begin()
            trace.begin()
            trace.close()
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(rows[1]['status'], 'incomplete')
            self.assertEqual(rows[-1]['status'], 'incomplete')

    def test_ack_timeout_is_recorded_without_changing_legacy_actions(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'lua.log'
            path.touch()
            controller, trace = Mock(), Mock()
            with patch('menu_runner.time.monotonic', side_effect=[0, 1]):
                reset_from_battle(controller, MenuTiming(), telemetry_log=path, trace=trace)
            trace.event.assert_any_call('dialog_ack_timeout', retries=0)
            controller.confirm_quit_to_main_menu.assert_called_once_with(0.08)

    def test_fresh_ack_avoids_timeout_but_stale_ack_does_not(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'lua.log'
            path.write_text('AUTOMATION_NATIVE_DIALOG=1|E\n')
            controller, trace = Mock(), Mock()
            def append_ack(delay):
                with path.open('a') as stream:
                    stream.write('AUTOMATION_NATIVE_DIALOG=1|E\n')
            controller.quit_to_main_menu.side_effect = append_ack
            with patch('menu_runner.time.monotonic', side_effect=[0, 0.1]):
                reset_from_battle(controller, MenuTiming(), telemetry_log=path, trace=trace)
            trace.event.assert_any_call('dialog_acknowledged', retries=0)
            controller.quit_to_main_menu.side_effect = None
            trace.reset_mock()
            with patch('menu_runner.time.monotonic', side_effect=[0, .1, 1]), patch('menu_runner.time.sleep'):
                reset_from_battle(controller, MenuTiming(), telemetry_log=path, trace=trace)
            trace.event.assert_any_call('dialog_ack_timeout', retries=1)
