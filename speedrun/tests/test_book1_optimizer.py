import json
import tempfile
import unittest
from pathlib import Path

from book1_optimizer import (
    TELEMETRY_SCHEMA_VERSION, DecisionOverrides, TransitionCorpus, action_key,
    candidate_payload, choose_recorded_lookahead, pareto_candidates,
    state_fingerprint, state_payload, transition_errors,
)
from deluxe_optimizer import Candidate, DeluxeState


def state(**changes):
    values = dict(
        sequence=1, board="TEST/ROAD/LINE/KEEP", gems=("none",) * 16,
        tile_powers=(0.0,) * 16, book=1, chapter=1, stage=1,
        enemy="Trojan Warrior", hp=2.0, max_hp=2.0, offense=0.0,
        treasures=frozenset(), overkill_thresholds=(),
    )
    values.update(changes)
    return DeluxeState(**values)


def candidate(word="TEST", path=(0, 1, 2, 3), damage=2.0, seconds=0.8):
    return Candidate(
        word, path, damage, damage - 2.0, None, damage >= 2.0,
        seconds, 0,
    )


class Book1OptimizerTests(unittest.TestCase):
    def test_fingerprint_ignores_sequence_but_not_board(self):
        self.assertEqual(state_fingerprint(state()), state_fingerprint(state(sequence=9)))
        self.assertNotEqual(
            state_fingerprint(state()), state_fingerprint(state(board="BEST/ROAD/LINE/KEEP"))
        )

    def test_transition_rejects_changed_unselected_letter(self):
        before = state()
        valid = state(sequence=2, board="ABCD/ROAD/LINE/KEEP", hp=2.0)
        invalid = state(sequence=2, board="ABCD/BOAD/LINE/KEEP", hp=2.0)
        self.assertEqual(transition_errors(before, candidate(), valid), [])
        self.assertIn("unselected tile 4 changed letter", transition_errors(
            before, candidate(), invalid
        ))

    def test_corpus_requires_two_validated_branches_before_override(self):
        before = state()
        first = candidate()
        second = candidate("ROAD", (4, 5, 6, 7), 2.0, 0.9)
        after_first = state(sequence=2, board="ABCD/ROAD/LINE/KEEP")
        after_second = state(sequence=2, board="TEST/ABCD/LINE/KEEP")
        rows = []
        for chosen, after, elapsed in (
            (first, after_first, 2.0), (second, after_second, 1.5),
        ):
            rows.append({
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "clean": True,
                "before": state_payload(before),
                "action": candidate_payload(chosen),
                "after": state_payload(after),
                "timing": {"ready_seconds": elapsed},
            })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timing.jsonl"
            path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
            one = TransitionCorpus.load(path)
            self.assertIsNone(choose_recorded_lookahead(before, (first, second), one))
            path.write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
            two = TransitionCorpus.load(path)
            self.assertEqual(
                choose_recorded_lookahead(before, (first, second), two), second
            )

    def test_pareto_collapses_same_tile_mask(self):
        slow = candidate(seconds=1.0)
        fast = candidate(seconds=0.7)
        self.assertEqual(pareto_candidates((slow, fast)), [fast])
        self.assertEqual(action_key("test", (0, 1)), "TEST:0,1")

    def test_exact_state_override_selects_only_legal_action(self):
        current = state()
        selected = candidate()
        overrides = DecisionOverrides({
            state_fingerprint(current): {
                "word": selected.word, "path": list(selected.path),
            }
        })
        self.assertIs(overrides.choose(current, [selected]), selected)
        with self.assertRaisesRegex(RuntimeError, "is not legal"):
            overrides.choose(current, [candidate("ROAD", (4, 5, 6, 7))])


if __name__ == "__main__":
    unittest.main()
