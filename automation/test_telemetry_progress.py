import tempfile
import sys
import unittest
from pathlib import Path

from telemetry_progress import TelemetryProgress
from tas_watchdog import run_watchdog


class ProgressTests(unittest.TestCase):
    def test_sequences_and_heartbeats_are_not_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory)/'lua.log'
            log.write_bytes(b'AUTOMATION_READY=OLD\n')
            reader = TelemetryProgress(log)
            self.assertFalse(reader.poll())
            with log.open('ab') as stream:
                stream.write(b'AUTOMATION_CONTEXT=1|2|-1|4|E\\r\\n')
            self.assertTrue(reader.poll())
            with log.open('ab') as stream:
                stream.write(b'AUTOMATION_CONTEXT=2|2|-1|4|E\\r\\nAUTOMATION_DIALOG_PULSE=1|99|E\n')
            self.assertFalse(reader.poll())
            with log.open('ab') as stream:
                stream.write(b'AUTOMATION_READY=ABCD/EFGH/IJKL/MNOP')
            self.assertFalse(reader.poll())
            with log.open('ab') as stream:
                stream.write(b'\n')
            self.assertTrue(reader.poll())

    def test_rotation_does_not_refresh_identical_state(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory)/'lua.log'
            reader = TelemetryProgress(log)
            log.write_text('AUTOMATION_READY=ABCD\n')
            self.assertTrue(reader.poll())
            replacement = Path(directory)/'new.log'
            replacement.write_text('AUTOMATION_READY=ABCD\n')
            replacement.replace(log)
            self.assertFalse(reader.poll())

    def test_chattering_process_is_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root/'child.py'
            child.write_text("import time\nfrom pathlib import Path\n"
                             "while True:\n"
                             " with Path('lua.log').open('a') as f: f.write('AUTOMATION_SYNC=1\\n')\n"
                             " time.sleep(.01)\n")
            code, packet = run_watchdog(command=[sys.executable, str(child)], repo=root,
                                       log=root/'lua.log', incidents=root/'incidents',
                                       stall_seconds=3, timeout_seconds=5,
                                       poll_seconds=.01, progress_seconds=.2, quiet=True)
            self.assertEqual(code, 124)
            self.assertIn('telemetry state unchanged', packet.read_text())


if __name__ == '__main__':
    unittest.main()
