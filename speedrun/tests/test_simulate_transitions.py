import json
import tempfile
import unittest
from pathlib import Path

from audit_transition_corpus import refill_layout
from book1_optimizer import state_payload
from deluxe_optimizer import DeluxeState
from simulate_transitions import compact_board, evaluate, replay


def observation():
    state = DeluxeState(sequence=1, board='TEST/ABCD/EFGH/IJKL',
                        gems=('none',)*16, tile_powers=(0.,)*16,
                        book=1, chapter=1, stage=1, enemy='Test', hp=10,
                        max_hp=10, offense=0, treasures=frozenset(),
                        overkill_thresholds=(0, 1, 2, 3))
    before = state_payload(state)
    after = dict(before, board='WORD/ABCD/EFGH/IJKL', hp=9, sequence=2)
    return dict(before=before, after=after, chapter=1, run_id='test',
                action=dict(word='TEST', path=[0, 1, 2, 3]),
                audit=dict(source_line=1, refill=refill_layout(
                    before['board'].replace('/', ''), after['board'].replace('/', ''), [0, 1, 2, 3])))


class SimulatorTests(unittest.TestCase):
    def test_column_gravity(self):
        result = compact_board('ABCD/EFGH/IJKL/MNOP', [8, 0], ['X', 'Y'])
        self.assertEqual(result['board'], 'XBCD/YFGH/EJKL/MNOP')
        self.assertEqual(result['replacement_slots'], [0, 4])

    def test_invalid_inputs(self):
        for path, refill in [([0, 0], ['X', 'Y']), ([16], ['X']), ([0], [])]:
            with self.assertRaises(ValueError):
                compact_board('ABCD/EFGH/IJKL/MNOP', path, refill)

    def test_hp_prediction_and_mismatch(self):
        row = observation()
        result = replay(row)
        row['after']['hp'] = result['predicted']['hp']
        self.assertEqual(replay(row)['mismatches'], [])
        row['after']['hp'] += .25
        self.assertEqual(replay(row)['mismatches'], ['enemy-hp'])

    def test_runs_remain_separate_and_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/'input.jsonl', Path(directory)/'report'
            first = observation()
            second = dict(first, run_id='other')
            source.write_text(json.dumps(first)+'\n'+json.dumps(second)+'\n')
            report = evaluate(source, output)
            self.assertEqual(len(report['groups']), 2)
            with self.assertRaises(FileExistsError):
                evaluate(source, output)

    def test_powered_damage_not_claimed_supported(self):
        row = observation()
        row['before']['player_damage_multiplier'] = 2
        self.assertIn('powered-up-damage', replay(row)['unsupported'])
