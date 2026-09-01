import tempfile
import unittest
from pathlib import Path

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
