import tempfile
import unittest
import contextlib
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

from auto_repair_loop import is_infrastructure_failure, read_repair_result
from failure_packet import build_packet, relevant_lines, stall_signature
from repair_loop import codex_command
from tas_watchdog import run_watchdog


class FailurePacketTests(unittest.TestCase):
    def test_prefers_automation_lines(self):
        lines = ["noise", "AUTOMATION_READY=ABC", "more noise"]
        self.assertEqual(relevant_lines(lines, 10), ["AUTOMATION_READY=ABC"])

    def test_signature_is_stable(self):
        lines = ["AUTOMATION_READY=ABC"]
        self.assertEqual(stall_signature("stalled", lines), stall_signature("stalled", lines))

    def test_packet_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "lua.log"
            log.write_text("".join(f"AUTOMATION_X={i}\n" for i in range(500)))
            packet = build_packet(
                repo=root, log=log, reason="test", command=["runner"],
                log_line_limit=20,
            )
            self.assertEqual(len(packet["log_tail"]), 20)


class WatchdogTests(unittest.TestCase):
    def test_quiet_monitor_keeps_final_lines_and_writes_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = root / 'status.json'
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code, packet = run_watchdog(
                    command=[sys.executable, '-c',
                             "print('12:00 INFO Attack 1: TEST'); "
                             "print('12:00 INFO State 2: Goat HP 3/3'); "
                             "print('12:00 WARNING retry')"],
                    repo=root, log=root/'lua.log', incidents=root/'incidents',
                    stall_seconds=2, timeout_seconds=3, poll_seconds=.01,
                    quiet=True, status_path=status,
                )
            self.assertEqual(code, 0)
            self.assertIsNone(packet)
            self.assertNotIn('Attack 1', output.getvalue())
            snapshot = json.loads(status.read_text())
            self.assertEqual(snapshot['status'], 'runner-exited')
            self.assertEqual(snapshot['attacks_submitted'], 1)
            self.assertEqual(snapshot['warning_count'], 1)
            self.assertIn('Goat', snapshot['latest_state'])
            self.assertFalse(snapshot['screenshots_enabled'])

    def test_crash_produces_packet_without_screenshot(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('tas_watchdog.capture_screenshot') as screenshot:
            root = Path(directory)
            code, path = run_watchdog(
                command=[sys.executable, '-c', "print('fatal detail', flush=True); exit(7)"],
                repo=root, log=root/'lua.log', incidents=root/'incidents',
                stall_seconds=2, timeout_seconds=3, poll_seconds=.01, quiet=True,
            )
            self.assertEqual(code, 7)
            packet = json.loads(path.read_text())
            self.assertIn('fatal detail', packet['process_output_tail'])
            screenshot.assert_not_called()

    def test_unterminated_output_does_not_block_stall_timer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, packet = run_watchdog(
                command=[sys.executable, '-c',
                         "import sys,time; sys.stdout.write('partial'); "
                         "sys.stdout.flush(); time.sleep(5)"],
                repo=root, log=root/'lua.log', incidents=root/'incidents',
                stall_seconds=.15, timeout_seconds=1, poll_seconds=.01, quiet=True,
            )
            self.assertEqual(code, 124)
            self.assertIn('unchanged', json.loads(packet.read_text())['reason'])

    def test_interrupt_stops_owned_child(self):
        from tas_watchdog import stop_process
        with tempfile.TemporaryDirectory() as directory, \
                patch('tas_watchdog.selectors.EpollSelector.select', side_effect=KeyboardInterrupt), \
                patch('tas_watchdog.stop_process', wraps=stop_process) as stop:
            root = Path(directory)
            with self.assertRaises(KeyboardInterrupt):
                run_watchdog(
                    command=[sys.executable, '-c', 'import time; time.sleep(5)'],
                    repo=root, log=root/'lua.log', incidents=root/'incidents',
                    stall_seconds=1, timeout_seconds=2, poll_seconds=.01, quiet=True,
                )
            process = stop.call_args.args[0]
            self.assertIsNotNone(process.poll())

    def test_stalled_log_writes_packet_and_returns_124(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "lua.log"
            log.write_text("AUTOMATION_READY=ABC\n")
            code, packet = run_watchdog(
                command=["bash", "-c", "sleep 5"], repo=root, log=log,
                incidents=root / "incidents", stall_seconds=0.15,
                timeout_seconds=None, poll_seconds=0.02,
                capture_screenshots=False,
            )
            self.assertEqual(code, 124)
            self.assertIsNotNone(packet)
            self.assertTrue(packet.exists())

    def test_successful_command_does_not_write_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, packet = run_watchdog(
                command=["bash", "-c", "true"], repo=root,
                log=root / "lua.log", incidents=root / "incidents",
                stall_seconds=1, timeout_seconds=None, poll_seconds=0.02,
                capture_screenshots=False,
            )
            self.assertEqual(code, 0)
            self.assertIsNone(packet)


class AutoRepairTests(unittest.TestCase):
    def test_codex_command_attaches_stall_screenshot(self):
        command = codex_command(
            Path("/repo"), Path("/result.json"), Path("/stall.png")
        )
        self.assertIn("--image", command)
        self.assertIn("/stall.png", command)

    def test_reads_safe_structured_result(self):
        with tempfile.TemporaryDirectory() as directory:
            result = Path(directory) / "result.json"
            result.write_text(
                '{"cause":"edge case","changed_files":[],"tests":[],"retry_safe":true}'
            )
            self.assertTrue(read_repair_result(result)["retry_safe"])

    def test_rejects_incomplete_result(self):
        with tempfile.TemporaryDirectory() as directory:
            result = Path(directory) / "result.json"
            result.write_text('{"retry_safe":true}')
            with self.assertRaises(ValueError):
                read_repair_result(result)

    def test_recognizes_sandbox_failure_without_changes(self):
        result = {
            "cause": "bwrap sandbox failed with RTM_NEWADDR",
            "changed_files": [],
            "tests": ["Not run: repository access blocked"],
            "retry_safe": False,
        }
        self.assertTrue(is_infrastructure_failure(result))

    def test_does_not_refund_real_failed_fix(self):
        result = {
            "cause": "stun recovery still stalls",
            "changed_files": ["speedrun/continuous_runner.py"],
            "tests": ["test failed"],
            "retry_safe": False,
        }
        self.assertFalse(is_infrastructure_failure(result))


if __name__ == "__main__":
    unittest.main()
