import json
import tempfile
import unittest
from pathlib import Path

from animation_report import animation_groups


class AnimationReportTests(unittest.TestCase):
    def test_groups_clean_samples_by_animation_and_diamond_use(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timing.jsonl"
            rows = [
                {
                    "clean": True,
                    "enemy_defeated": True,
                    "action": {
                        "word": "SAPPHIRE", "tier": "sapphire",
                        "gem_types": ["diamond"], "lethal": True,
                        "animation_class": "wow-overkill",
                    },
                    "timing": {"resolution_seconds": 3.0},
                },
                {
                    "clean": True,
                    "enemy_defeated": True,
                    "action": {
                        "word": "SAPPHIRE", "tier": "sapphire",
                        "gem_types": ["diamond"], "lethal": True,
                        "animation_class": "wow-overkill",
                    },
                    "timing": {"resolution_seconds": 5.0},
                },
            ]
            path.write_text(
                "\n".join(json.dumps(row) for row in rows), encoding="utf-8",
            )

            groups = animation_groups(path)

            self.assertEqual(groups[0]["samples"], 2)
            self.assertEqual(groups[0]["median_seconds"], 4.0)
            self.assertTrue(groups[0]["uses_diamond"])


if __name__ == "__main__":
    unittest.main()
