import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from new_run import last_user, profile_path, recreate_profile


class NewRunTests(unittest.TestCase):
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
    def test_fresh_run_confirms_intro_skip(
        self, _sleep, users, _last_user, profile, wait_for_profile,
        _start_timer, _record_chapter, _save_state,
    ):
        users.glob.return_value = []
        profile.return_value = Path("Lex10.bwa")
        wait_for_profile.side_effect = [None, Path("Lex10.bwa")]
        controller = Mock()

        recreate_profile(controller, "Lex10", timer_path=None)

        controller.skip_intro.assert_called_once_with(1.0)
        controller.confirm_skip_intro.assert_called_once_with(0.8)
        self.assertLess(
            controller.method_calls.index(unittest.mock.call.skip_intro(1.0)),
            controller.method_calls.index(unittest.mock.call.confirm_skip_intro(0.8)),
        )


if __name__ == "__main__":
    unittest.main()
