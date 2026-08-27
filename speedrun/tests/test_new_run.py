import tempfile
import unittest
from pathlib import Path

from new_run import last_user, profile_path


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


if __name__ == "__main__":
    unittest.main()
