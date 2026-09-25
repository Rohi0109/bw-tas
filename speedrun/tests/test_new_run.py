import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from new_run import (
    bridge_runner_startup_dialogue, last_user, log_suffix_contains,
    profile_path, recreate_profile,
    skip_intro_until_chapter,
)


class NewRunTests(unittest.TestCase):
    @patch("new_run.time.sleep")
    def test_startup_bridge_clicks_only_confirmed_convpanel(self, _sleep):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text(
                "AUTOMATION_DIALOG_PULSE=convpanel|3|1|E\n"
                "AUTOMATION_PLAY_TUTORIAL=4|E\n"
                "AUTOMATION_DIALOG_PULSE=convpanel|3|2|E\n",
                encoding="utf-8",
            )
            controller = Mock()

            bridge_runner_startup_dialogue(
                controller, log, 0, timeout=0.01,
            )

        controller.advance_dialog.assert_called_once_with("convpanel", 0.01)

    def test_log_suffix_ignores_stale_chapter_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text("Book:StartGame called stale\n", encoding="utf-8")
            offset = log.stat().st_size
            self.assertFalse(log_suffix_contains(log, offset, "Book:StartGame called"))
            with log.open("a", encoding="utf-8") as output:
                output.write("Book:StartGame called fresh\n")
            self.assertTrue(log_suffix_contains(log, offset, "Book:StartGame called"))

    @patch("new_run.time.sleep")
    def test_intro_accepts_fresh_board_when_startgame_predates_boundary(self, _sleep):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text("Book:StartGame called stale\n", encoding="utf-8")
            offset = log.stat().st_size
            with log.open("a", encoding="utf-8") as output:
                output.write("AUTOMATION_BOARD=SFAE/PFUN/RJDY/TLIS\n")
            controller = Mock()

            skip_intro_until_chapter(controller, log, offset)

        controller.skip_intro.assert_not_called()
        controller.confirm_skip_intro.assert_not_called()

    @patch("new_run.time.sleep")
    def test_intro_recovers_lua_wait_before_clicking_intro(self, _sleep):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text("", encoding="utf-8")
            offset = 0
            controller = Mock()

            def resume(_delay):
                with log.open("a", encoding="utf-8") as output:
                    output.write("AUTOMATION_BOARD=SFAE/PFUN/RJDY/TLIS\n")

            controller.resume_lua_runtime.side_effect = resume
            log.write_text(
                "Program in waiting. Type go() or press F5 to continue execution.\n",
                encoding="utf-8",
            )

            skip_intro_until_chapter(controller, log, offset, timeout=0.2)

        controller.resume_lua_runtime.assert_called_once_with(0.15)
        controller.skip_intro.assert_not_called()
        controller.confirm_skip_intro.assert_not_called()

    def test_last_user_reads_wine_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "user.reg"
            registry.write_text(
                '[Software\\PopCap\\Bookworm]\n"LastUser"="lex10"\n',
                encoding="utf-8",
            )

            self.assertEqual(last_user(registry), "lex10")

    def test_profile_lookup_is_case_insensitive_and_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            users = Path(directory)
            expected = users / "lex10.bwa"
            expected.write_bytes(b"new run")
            (users / "Lex.bwa").write_bytes(b"protected")

            self.assertEqual(profile_path("Lex10", users), expected)

    def test_profile_lookup_refuses_missing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "exactly one save"):
                profile_path("Lex10", Path(directory))

    @patch("new_run.save_state")
    @patch("new_run.save_run_history")
    @patch("new_run.record_chapter")
    @patch("new_run.start_timer")
    @patch("new_run.wait_for_profile")
    @patch("new_run.profile_path")
    @patch("new_run.last_user", return_value="Lex10")
    @patch("new_run.USERS")
    @patch("new_run.time.sleep")
    @patch("new_run.bridge_runner_startup_dialogue")
    @patch("new_run.skip_intro_until_chapter")
    def test_fresh_run_confirms_intro_skip(
        self, intro, bridge, _sleep, users, _last_user, profile, wait_for_profile,
        _start_timer, _record_chapter, _save_history, _save_state,
    ):
        users.glob.return_value = []
        profile.return_value = Path("Lex10.bwa")
        wait_for_profile.side_effect = [None, Path("Lex10.bwa")]
        controller = Mock()
        controller.replace_user_name.return_value = 123.5
        _start_timer.return_value = {
            "started_at": 123.5, "started_at_iso": "confirmed",
        }
        timer_path = Path("timer.json")

        recreate_profile(controller, "Lex10", timer_path=timer_path)

        _start_timer.assert_called_once_with(timer_path, timestamp=123.5)
        _record_chapter.assert_called_once_with(
            _start_timer.return_value, 1, 1, 123.5,
        )
        _save_history.assert_called_once_with(_start_timer.return_value)
        intro.assert_called_once()
        bridge.assert_called_once()


if __name__ == "__main__":
    unittest.main()
