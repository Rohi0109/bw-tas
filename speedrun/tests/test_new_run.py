import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from new_run import last_user, log_suffix_contains, profile_path, recreate_profile


class NewRunTests(unittest.TestCase):
    def test_log_suffix_ignores_stale_chapter_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text("Book:StartGame called stale\n", encoding="utf-8")
            offset = log.stat().st_size
            self.assertFalse(log_suffix_contains(log, offset, "Book:StartGame called"))
            with log.open("a", encoding="utf-8") as output:
                output.write("Book:StartGame called fresh\n")
            self.assertTrue(log_suffix_contains(log, offset, "Book:StartGame called"))

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
    @patch("new_run.record_chapter")
    @patch("new_run.start_timer")
    @patch("new_run.wait_for_profile")
    @patch("new_run.profile_path")
    @patch("new_run.last_user", return_value="Lex10")
    @patch("new_run.USERS")
    @patch("new_run.time.sleep")
    @patch("new_run.skip_intro_until_chapter")
    def test_fresh_run_confirms_intro_skip(
        self, intro, _sleep, users, _last_user, profile, wait_for_profile,
        _start_timer, _record_chapter, _save_state,
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
        intro.assert_called_once()


if __name__ == "__main__":
    unittest.main()
