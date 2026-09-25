import copy
import unittest

from audit_transition_corpus import classify, refill_layout


def sample():
    before = dict(board='TEST/AAAA/AAAA/AAAA', sequence=1, hp=5,
                  enemy='Siren', book=1, chapter=-1, stage=2,
                  gems=['none'] * 16, tile_powers=[0] * 16,
                  selectable=[True] * 16, zero_damage=[False] * 16)
    after = dict(before, board='WORD/AAAA/AAAA/AAAA', sequence=2, hp=3)
    return dict(before=before, after=after, action=dict(word='TEST', path=[0, 1, 2, 3]),
                clean=True, chapter=3, timing=dict(input_attempts=1, input_seconds=.1, ready_seconds=3))


class AuditTests(unittest.TestCase):
    def test_usable_observation_retains_unknown_context(self):
        row = sample()
        original = copy.deepcopy(row)
        reasons, notes = classify(row)
        self.assertEqual(reasons, [])
        self.assertIn('rng-unavailable', notes)
        self.assertIn('before-chapter-from-outer-context', notes)
        self.assertEqual(row, original)

    def test_clean_flag_does_not_admit_stale_ack(self):
        row = sample()
        row['after'] = dict(row['before'])
        reasons, _ = classify(row)
        self.assertIn('nonadvancing-sequence', reasons)
        self.assertIn('unchanged-board-hp-enemy', reasons)

    def test_changed_unused_tile_is_quarantined(self):
        row = sample()
        row['after']['board'] = 'WORD/BAAA/AAAA/AAAA'
        self.assertIn('column-survivors-mismatch', classify(row)[0])

    def test_recorded_patinated_column_gravity(self):
        result = refill_layout(
            'NDGIATOZEPAOTOWP', 'NAECIFGZASOOIOWP',
            [9, 4, 5, 3, 0, 10, 12, 8, 1])
        self.assertIsNotNone(result)
        self.assertIn([2, 6], result['survivor_mapping'])
        self.assertEqual(len(result['replacement_slots']), 9)

    def test_cross_enemy_is_not_a_damage_training_pair(self):
        row = sample()
        row['after']['enemy'] = 'Sea Witch'
        self.assertIn('encounter-transition-needs-route-validation', classify(row)[0])

    def test_invalid_path_and_timing_are_rejected(self):
        row = sample()
        row['action']['path'] = [-1, 1, 2, 3]
        row['timing']['ready_seconds'] = float('nan')
        self.assertIn('invalid-path', classify(row)[0])
        self.assertIn('invalid-timing', classify(row)[0])
