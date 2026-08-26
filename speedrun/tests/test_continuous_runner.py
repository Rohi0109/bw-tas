import tempfile
import unittest
from pathlib import Path

from continuous_runner import read_seed


class ContinuousRunnerTests(unittest.TestCase):
    def test_new_board_clears_stale_ready_state(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text(
                "AUTOMATION_READY=ABCD/EFGH/IJKL/MNOP\n"
                "AUTOMATION_BOARD=BCDE/FGHI/JKLM/NOPQ\n",
                encoding="utf-8",
            )

            board, ready, done, chapter = read_seed(log)

        self.assertEqual(board, "BCDE/FGHI/JKLM/NOPQ")
        self.assertFalse(ready)
        self.assertFalse(done)
        self.assertIsNone(chapter)


if __name__ == "__main__":
    unittest.main()
