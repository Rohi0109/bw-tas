import unittest

from compare_two_hit_fights import plain_rack, submission_id, survivor_plans
from test_deluxe_optimizer import state


class TwoHitTests(unittest.TestCase):
    def test_second_word_uses_only_unconsumed_tiles(self):
        current = state(board='TEST/WORD/AAAA/AAAA', hp=1.75)
        plans = survivor_plans(current, ['TEST', 'WORD'])
        self.assertTrue(plans)
        for plan in plans:
            first, second = plan['first'], plan['second']
            self.assertIsNotNone(second)
            self.assertFalse(set(first['path']) & set(second['path']))
            self.assertGreaterEqual(first['damage']+second['damage'], current.hp)

    def test_refill_is_not_invented(self):
        current = state(board='TEST/AAAA/AAAA/AAAA', hp=1.5)
        self.assertEqual(survivor_plans(current, ['TEST']), [])

    def test_plain_duplicate_tiles_can_supply_two_copies(self):
        current = state(board='TEST/TEST/AAAA/AAAA', hp=1.5)
        plan = survivor_plans(current, ['TEST'])[0]
        self.assertEqual(plan['first']['path'], [0, 1, 2, 3])
        self.assertEqual(plan['second']['path'], [4, 5, 6, 7])

    def test_unsupported_status_or_gems_are_rejected(self):
        for current in [state(player_stunned=True), state(gems=('ruby',)*16)]:
            self.assertFalse(plain_rack(current))
            with self.assertRaises(ValueError):
                survivor_plans(current, ['AAA'])

    def test_native_submission_must_match_recorded_action(self):
        row = dict(before=dict(enemy='Siren'), action=dict(word='TEST'),
                   native_attack_events=['AUTOMATION_ATTACK_ID=1|Siren|TEST|E'])
        self.assertEqual(submission_id(row), 1)
        row['action']['word'] = 'OTHER'
        self.assertIsNone(submission_id(row))

    def test_one_hit_kill_does_not_require_second_word(self):
        plan = survivor_plans(state(board='TEST/AAAA/AAAA/AAAA', hp=.75), ['TEST'])[0]
        self.assertIsNone(plan['second'])
