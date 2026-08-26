import tempfile
import unittest
from pathlib import Path

from continuous_runner import (
    read_latest_dialog, read_screen_blocker, read_seed, sphinx_candidate,
)
from deluxe_optimizer import Candidate


class ContinuousRunnerTests(unittest.TestCase):
    def test_treasure_screen_is_recovered_as_click_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text(
                "AUTOMATION_DIALOG=conversation|8|E\n"
                "AUTOMATION_DIALOG=treasure|9|E\n",
                encoding="utf-8",
            )

            self.assertEqual(read_screen_blocker(log), "treasure")

    def test_later_combat_dialog_state_clears_treasure_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text(
                "AUTOMATION_DIALOG=treasure|9|E\n"
                "AUTOMATION_DIALOG=none|10|E\n",
                encoding="utf-8",
            )

            self.assertIsNone(read_screen_blocker(log))

    def test_active_levelup_is_recovered_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text(
                "AUTOMATION_DIALOG=none|14|E\n"
                "AUTOMATION_DIALOG=levelup|15|E\n",
                encoding="utf-8",
            )

            self.assertEqual(read_latest_dialog(log), "levelup")
            self.assertIsNone(read_screen_blocker(log))

    def test_sphinx_uses_fixed_answer(self):
        normal = Candidate("PROPELLED", (0,), 9, 0, None, True, 1.2, 0)
        answer = Candidate("SKY", (1, 2, 3), 1, -8, None, False, 0.6, 0)

        selected, expected = sphinx_candidate(
            "Sphinx (Riddle 1 of 5)", [normal, answer]
        )

        self.assertIs(selected, answer)
        self.assertEqual(expected, "SKY")

    def test_sphinx_missing_answer_allows_solver_fallback(self):
        normal = Candidate("PROPELLED", (0,), 9, 0, None, True, 1.2, 0)

        selected, expected = sphinx_candidate(
            "Sphinx (Riddle 1 of 5)", [normal]
        )

        self.assertIsNone(selected)
        self.assertEqual(expected, "SKY")

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
