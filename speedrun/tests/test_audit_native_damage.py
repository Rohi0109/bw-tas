import unittest
from unittest.mock import patch

from audit_native_damage import audit_text
from book1_optimizer import state_from_payload
from test_simulate_transitions import observation


class NativeDamageAuditTests(unittest.TestCase):
    def test_pre_submission_trace_exposes_changed_post_submission_value(self):
        rows = self.audit('AUTOMATION_ATTACK_ID=1|Test|TEST|E\n'
                          'AUTOMATION_DAMAGE_TRACE=1|4|4|0.5|0.5|0|0,1,2,3|E\n'
                          'AUTOMATION_DAMAGE_TABLE=1|0,0,0.25,0.5|E\n'
                          'AUTOMATION_NATIVE_WORD_VALUE=TEST|5|5|Test|E')
        self.assertTrue(rows[0]['pre_submit_tier_matches'])
        self.assertTrue(rows[0]['value_changed_after_submission'])
        self.assertEqual(rows[0]['pre_submit_trace']['selected_slots'], [0, 1, 2, 3])
        self.assertEqual(rows[0]['native_damage_table'], [0, 0, .25, .5])

    def test_trace_from_another_attack_cannot_attach(self):
        rows = self.audit('AUTOMATION_ATTACK_ID=1|Test|TEST|E\n'
                          'AUTOMATION_DAMAGE_TRACE=2|4|4|0.5|0.5|0|0,1,2,3|E')
        self.assertNotIn('pre_submit_trace', rows[0])

    def audit(self, events, **changes):
        payload = dict(observation()['before'], **changes)
        with patch('audit_native_damage.parse_state', return_value=state_from_payload(payload)):
            return audit_text('AUTOMATION_READY_SEQ=1|E\n' + events)

    def test_identity_matches_and_retains_healing_separately(self):
        rows = self.audit('AUTOMATION_ATTACK_ID=1|Test|TEST|E\n'
                          'AUTOMATION_NATIVE_WORD_VALUE=TEST|4|4|Test|E\n'
                          'AUTOMATION_ATTACK_HP=99|10|1|E\n'
                          'AUTOMATION_ATTACK_HP=1|10|9.25|E\n'
                          'AUTOMATION_ATTACK_HP=1|9.25|10|E')
        self.assertTrue(rows[0]['tier_matches'])
        self.assertTrue(rows[0]['hp_matches'])
        self.assertTrue(rows[0]['nonlethal_damage_check'])
        self.assertEqual(rows[0]['hp_events'], [[10, 9.25], [9.25, 10]])

    def test_console_replay_is_not_a_second_attack(self):
        block = ('AUTOMATION_ATTACK_ID=1|Test|TEST|E\n'
                 'AUTOMATION_ATTACK_HP=1|10|0|E\n')
        rows = self.audit(block + '> \b ' + block)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]['hp_events']), 1)
        self.assertFalse(rows[0]['nonlethal_damage_check'])

    def test_conflicting_reused_id_refuses_cross_session_join(self):
        with self.assertRaises(ValueError):
            self.audit('AUTOMATION_ATTACK_ID=1|Test|TEST|E\n'
                       'AUTOMATION_ATTACK_ID=1|Other|TEST|E')

    def test_gem_path_is_not_guessed(self):
        rows = self.audit('AUTOMATION_ATTACK_ID=1|Test|TEST|E',
                          tile_powers=[.5]+[0]*15)
        self.assertNotIn('modeled_damage', rows[0])
        self.assertIn('damage-outside-plain-rack-scope', rows[0]['issues'])

    def test_mismatched_value_word_is_ignored(self):
        rows = self.audit('AUTOMATION_ATTACK_ID=1|Test|TEST|E\n'
                          'AUTOMATION_NATIVE_WORD_VALUE=OTHER|5|5|Test|E')
        self.assertNotIn('native_tier', rows[0])
