import tempfile
import unittest
from pathlib import Path

from continuous_runner import (
    is_initial_play_tutorial, is_unchanged_combat_snapshot,
    read_latest_dialog, read_screen_blocker, read_seed, sphinx_candidate,
)
from deluxe_optimizer import Candidate, DeluxeState


class ContinuousRunnerTests(unittest.TestCase):
    @staticmethod
    def state(sequence, board="ABCD/EFGH/IJKL/MNOP", hp=3):
        return DeluxeState(
            sequence, board, ("none",) * 16, (0.0,) * 16,
            1, 2, 3, "Cyclops", hp, 5, 0, frozenset(), (),
        )

    def test_sequence_churn_does_not_replay_unchanged_combat(self):
        submitted = self.state(10)

        self.assertTrue(is_unchanged_combat_snapshot(self.state(11), submitted))
        self.assertFalse(
            is_unchanged_combat_snapshot(self.state(11, hp=2.5), submitted)
        )
        self.assertFalse(
            is_unchanged_combat_snapshot(
                self.state(11, board="BCDE/FGHI/JKLM/NOPQ"), submitted
            )
        )

    def test_only_fresh_profile_play_board_triggers_tutorial_override(self):
        board = "SFAE/PFUN/RJDY/TLIS"

        self.assertTrue(is_initial_play_tutorial(board, "levelup", None, 0))
        self.assertTrue(is_initial_play_tutorial(board, "levelup", object(), 0))
        self.assertFalse(is_initial_play_tutorial(board, "conversation", None, 0))
        self.assertFalse(is_initial_play_tutorial(board, "levelup", None, 1))
        self.assertFalse(is_initial_play_tutorial("PLAY/AAAA/AAAA/AAAA", "levelup", None, 0))

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
