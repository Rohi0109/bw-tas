import sys
import os
import unittest

# Allow importing from the automation package (two levels up from speedrun/tests/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'automation'))

from native_enemy_ai import (
    UrgencyLevel,
    assemble_hook_attacks,
    choose_attack,
    convert_hook_attack_types,
    get_urgency,
    normalise_attack,
    tick_counters,
    urgency_weight,
)


def atk(name='A', min=2, max=5, state='active', already_performed=False,
        damage=1.0, rate_counter=0):
    return dict(name=name, min=min, max=max, state=state,
                already_performed=already_performed, damage=damage,
                rate_counter=rate_counter)


def draw_returning(value):
    """Return a draw callable that always yields the given integer."""
    def _draw(label):
        return value
    return _draw


class UrgencyWeightTests(unittest.TestCase):
    def test_below_min_is_zero(self):
        self.assertEqual(urgency_weight(atk(min=3, max=6), 2), 0)

    def test_at_min_is_positive(self):
        self.assertGreater(urgency_weight(atk(min=3, max=6), 3), 0)
        self.assertLess(urgency_weight(atk(min=3, max=6), 3), 100)

    def test_at_max_is_100(self):
        self.assertEqual(urgency_weight(atk(min=2, max=5), 5), 100)

    def test_past_max_is_100(self):
        self.assertEqual(urgency_weight(atk(min=2, max=5), 9), 100)

    def test_max_zero_below_min_is_zero(self):
        self.assertEqual(urgency_weight(atk(min=3, max=0), 2), 0)

    def test_max_zero_at_or_above_min_never_100(self):
        # max=0 < min=2 → sentinel → weight=1, never due
        self.assertEqual(urgency_weight(atk(min=2, max=0), 100), 1)

    def test_max_equals_min_is_100_at_threshold(self):
        self.assertEqual(urgency_weight(atk(min=3, max=3), 3), 100)

    def test_max_less_than_min_returns_1_when_eligible(self):
        # max=-1 (no-bound sentinel): weight=1 when counter >= min
        self.assertEqual(urgency_weight(atk(min=2, max=-1), 5), 1)
        self.assertEqual(urgency_weight(atk(min=2, max=-1), 2), 1)
        self.assertEqual(urgency_weight(atk(min=2, max=-1), 1), 0)

    def test_weight_increases_with_counter(self):
        w2 = urgency_weight(atk(min=2, max=10), 2)
        w6 = urgency_weight(atk(min=2, max=10), 6)
        w10 = urgency_weight(atk(min=2, max=10), 10)
        self.assertLess(w2, w6)
        self.assertLess(w6, w10)
        self.assertEqual(w10, 100)

    def test_matches_campaign_simulator_formula(self):
        import math
        for minimum, maximum, counter in [(0, 5, 3), (2, 8, 5), (1, 1, 1), (3, 0, 5)]:
            a = atk(min=minimum, max=maximum)
            expected = (0 if counter < minimum
                        else 100 if maximum == minimum
                        else 1 if maximum < minimum
                        else min(100, max(1, math.floor(100*(counter-minimum+1)/(maximum-minimum+1)))))
            with self.subTest(min=minimum, max=maximum, counter=counter):
                self.assertEqual(urgency_weight(a, counter), expected)


class GetUrgencyTests(unittest.TestCase):
    def test_below_min_is_low(self):
        self.assertEqual(get_urgency(atk(min=3, max=6), 2), UrgencyLevel.LOW)

    def test_at_min_is_medium(self):
        self.assertEqual(get_urgency(atk(min=3, max=6), 3), UrgencyLevel.MEDIUM)

    def test_between_min_and_max_is_medium(self):
        self.assertEqual(get_urgency(atk(min=2, max=5), 4), UrgencyLevel.MEDIUM)

    def test_at_max_is_high(self):
        self.assertEqual(get_urgency(atk(min=2, max=5), 5), UrgencyLevel.HIGH)

    def test_past_max_is_high(self):
        self.assertEqual(get_urgency(atk(min=2, max=5), 9), UrgencyLevel.HIGH)

    def test_max_zero_never_high(self):
        self.assertEqual(get_urgency(atk(min=2, max=0), 100), UrgencyLevel.MEDIUM)

    def test_max_zero_below_min_is_low(self):
        self.assertEqual(get_urgency(atk(min=3, max=0), 2), UrgencyLevel.LOW)

    def test_max_equals_min_at_threshold_is_high(self):
        self.assertEqual(get_urgency(atk(min=3, max=3), 3), UrgencyLevel.HIGH)


class ChooseAttackTests(unittest.TestCase):
    def test_single_eligible_attack_no_draw_needed(self):
        # Single eligible DUE attack (weight=100): no draw consumed.
        attacks = [atk(min=2, max=5)]  # at counter=5, weight=100 (due)
        self.assertEqual(choose_attack(attacks, [5], None), 0)

    def test_no_eligible_attacks_returns_none(self):
        attacks = [atk(min=5, max=10)]
        self.assertIsNone(choose_attack(attacks, [2], None))

    def test_single_non_due_eligible_consumes_draw(self):
        # A sole non-due eligible attack must still consume ai-weighted draw.
        attacks = [atk(min=0, max=5)]  # counter=2, weight=50 (non-due)
        result = choose_attack(attacks, [2], draw_returning(0))
        self.assertEqual(result, 0)

    def test_single_non_due_eligible_none_draw_raises(self):
        # draw=None raises ValueError when only a weighted draw could decide.
        attacks = [atk(min=0, max=5)]  # counter=2, weight=50 (non-due)
        with self.assertRaises(ValueError):
            choose_attack(attacks, [2], None)

    def test_inactive_attack_not_eligible(self):
        attacks = [atk(min=0, max=5, state='inactive'), atk(min=0, max=5)]
        self.assertEqual(choose_attack(attacks, [3, 3], draw_returning(0)), 1)

    def test_already_performed_not_eligible(self):
        attacks = [atk(min=0, max=5, already_performed=True), atk(min=0, max=5)]
        self.assertEqual(choose_attack(attacks, [3, 3], draw_returning(0)), 1)

    def test_all_attacks_ineligible_returns_none(self):
        attacks = [atk(min=5, max=10, name='X'), atk(min=8, max=12, name='Y')]
        self.assertIsNone(choose_attack(attacks, [0, 0], None))

    def test_single_due_attack_no_draw(self):
        # Attack 0 medium, Attack 1 due: one due → no draw needed.
        attacks = [atk(min=2, max=5, name='M'), atk(min=2, max=5, name='H')]
        self.assertEqual(choose_attack(attacks, [2, 5], None), 1)

    def test_multiple_due_consumes_draw_draw0(self):
        # Both counters at max → both due. draw returns 0 → due[0 % 2] = index 0.
        attacks = [atk(min=2, max=5, name='A'), atk(min=2, max=5, name='B')]
        self.assertEqual(choose_attack(attacks, [5, 5], draw_returning(0)), 0)

    def test_multiple_due_consumes_draw_draw1(self):
        # draw returns 1 → due[1 % 2] = index 1. Matches campaign_simulator behavior.
        attacks = [atk(min=2, max=5, name='A'), atk(min=2, max=5, name='B')]
        self.assertEqual(choose_attack(attacks, [5, 5], draw_returning(1)), 1)

    def test_multiple_due_no_draw_raises(self):
        attacks = [atk(min=2, max=5, name='A'), atk(min=2, max=5, name='B')]
        with self.assertRaises(ValueError):
            choose_attack(attacks, [5, 5], None)

    def test_weighted_selection_consumes_draw(self):
        # Two MEDIUM attacks each with some weight; draw=0 → first attack selected.
        attacks = [atk(min=2, max=5, name='A'), atk(min=2, max=5, name='B')]
        result = choose_attack(attacks, [3, 3], draw_returning(0))
        self.assertEqual(result, 0)

    def test_weighted_selection_draw_chooses_second(self):
        # Attacks with weight 50 each; total=100; draw returns 50 → value=50,
        # 50 >= weight(50) of attack 0, so moves to attack 1 and 50-50=0 < 50 → attack 1.
        attacks = [atk(min=2, max=5, name='A'), atk(min=2, max=5, name='B')]
        result = choose_attack(attacks, [3, 3], draw_returning(50))
        self.assertEqual(result, 1)

    def test_weighted_no_draw_raises(self):
        attacks = [atk(min=2, max=5, name='A'), atk(min=2, max=5, name='B')]
        with self.assertRaises(ValueError):
            choose_attack(attacks, [3, 3], None)

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            choose_attack([atk()], [0, 0], None)

    def test_draw_label_passed(self):
        # Verify the draw callable receives a label string.
        labels = []
        def _draw(label):
            labels.append(label)
            return 0
        attacks = [atk(min=2, max=5, name='A'), atk(min=2, max=5, name='B')]
        choose_attack(attacks, [5, 5], _draw)
        self.assertTrue(labels)
        self.assertIsInstance(labels[0], str)


class TickCountersTests(unittest.TestCase):
    def test_all_increment_when_no_active(self):
        self.assertEqual(tick_counters([0, 2, 5], None), [1, 3, 6])

    def test_active_attack_resets_to_zero(self):
        self.assertEqual(tick_counters([3, 1, 7], 1), [4, 0, 8])

    def test_active_index_zero(self):
        self.assertEqual(tick_counters([5, 2], 0), [0, 3])

    def test_active_last_index(self):
        self.assertEqual(tick_counters([1, 2, 3], 2), [2, 3, 0])

    def test_does_not_mutate_input(self):
        original = [1, 2, 3]
        tick_counters(original, 0)
        self.assertEqual(original, [1, 2, 3])

    def test_empty_list(self):
        self.assertEqual(tick_counters([], None), [])


class NormaliseAttackTests(unittest.TestCase):
    """Parser-to-state-to-AI integration: hook field names → canonical → choose_attack."""

    def test_lua_hook_translates_to_canonical(self):
        hook = {'mMin': 1, 'mMax': 5, 'mAlreadyPerformed': False, 'mDamage': 2.0, 'mState': 0}
        canonical = normalise_attack(hook)
        self.assertEqual(canonical['min'], 1)
        self.assertEqual(canonical['max'], 5)
        self.assertFalse(canonical['already_performed'])
        self.assertEqual(canonical['damage'], 2.0)
        self.assertEqual(canonical['native_state_raw'], 0)
        self.assertNotIn('state', canonical)

    def test_already_performed_true_makes_attack_ineligible(self):
        # mAlreadyPerformed=True must reach already_performed so AI skips the attack.
        hook = {'mMin': 1, 'mMax': 5, 'mAlreadyPerformed': True, 'mDamage': 2.0, 'mState': 0}
        canonical = normalise_attack(hook)
        result = choose_attack([canonical], [2], None)
        self.assertIsNone(result)

    def test_already_performed_false_attack_eligible(self):
        hook = {'mMin': 1, 'mMax': 5, 'mAlreadyPerformed': False, 'mDamage': 2.0, 'mState': 0}
        canonical = normalise_attack(hook)
        result = choose_attack([canonical], [2], draw_returning(0))
        self.assertEqual(result, 0)

    def test_mstate_preserved_not_mapped_to_state(self):
        hook = {'mMin': 2, 'mMax': 5, 'mState': 1}
        canonical = normalise_attack(hook)
        self.assertIn('native_state_raw', canonical)
        self.assertEqual(canonical['native_state_raw'], 1)
        self.assertNotIn('state', canonical)

    def test_mixed_format_rejected(self):
        with self.assertRaises(ValueError):
            normalise_attack({'min': 1, 'max': 5, 'mAlreadyPerformed': False})

    def test_unknown_m_key_rejected(self):
        with self.assertRaises(ValueError):
            normalise_attack({'mMin': 1, 'mMax': 5, 'mUnknownField': 'x'})

    def test_canonical_format_passes_through(self):
        canonical = {'min': 2, 'max': 5, 'already_performed': False}
        result = normalise_attack(canonical)
        self.assertEqual(result, canonical)

    def test_unknown_canonical_key_rejected(self):
        with self.assertRaises(ValueError):
            normalise_attack({'min': 2, 'max': 5, 'unknown_field': True})

    def test_complete_hook_format_with_rate_counter(self):
        """Full hook attack dict (as Lua emits it) must pass normalise_attack."""
        hook = {'mMin': 1, 'mMax': 5, 'mRateCounter': 2,
                'mAlreadyPerformed': False, 'mDamage': 2.0, 'mState': 0}
        canonical = normalise_attack(hook)
        self.assertEqual(canonical['rate_counter'], 2)
        self.assertIn('native_state_raw', canonical)


class TypeConversionTests(unittest.TestCase):
    def test_string_false_becomes_bool_false(self):
        raw = {'mMin': '1', 'mMax': '5', 'mAlreadyPerformed': 'false',
               'mDamage': '2.0', 'mState': '0', 'mRateCounter': '2'}
        typed = convert_hook_attack_types(raw)
        self.assertIs(typed['mAlreadyPerformed'], False)
        self.assertIsInstance(typed['mMin'], int)
        self.assertIsInstance(typed['mDamage'], float)

    def test_string_true_becomes_bool_true(self):
        raw = {'mMin': '1', 'mMax': '1', 'mAlreadyPerformed': 'true',
               'mDamage': '1.0', 'mState': '0', 'mRateCounter': '1'}
        typed = convert_hook_attack_types(raw)
        self.assertIs(typed['mAlreadyPerformed'], True)

    def test_nil_value_raises(self):
        with self.assertRaises(ValueError):
            convert_hook_attack_types({'mMin': 'nil', 'mMax': '5'})

    def test_string_false_truthy_bug_fixed(self):
        # 'false' as a raw string is truthy in Python — conversion must fix this.
        raw = {'mMin': '1', 'mMax': '1', 'mAlreadyPerformed': 'false',
               'mDamage': '1.0', 'mState': '0', 'mRateCounter': '1'}
        typed = convert_hook_attack_types(raw)
        canonical = normalise_attack(typed)
        # already_performed=False → attack is eligible, not excluded
        result = choose_attack([canonical], [1], draw_returning(0))
        self.assertEqual(result, 0)

    def test_complete_hook_pipeline_already_performed_true(self):
        """String 'true' from parser must exclude the attack in AI."""
        raw = {'mMin': '1', 'mMax': '1', 'mAlreadyPerformed': 'true',
               'mDamage': '1.0', 'mState': '0', 'mRateCounter': '1'}
        typed = convert_hook_attack_types(raw)
        canonical = normalise_attack(typed)
        result = choose_attack([canonical], [1], None)
        self.assertIsNone(result)

    def test_nan_damage_rejected_at_conversion(self):
        with self.assertRaises(ValueError):
            convert_hook_attack_types({'mMin': '1', 'mMax': '1', 'mDamage': 'nan'})

    def test_inf_damage_rejected_at_conversion(self):
        with self.assertRaises(ValueError):
            convert_hook_attack_types({'mMin': '1', 'mMax': '1', 'mDamage': 'inf'})

    def test_neg_inf_damage_rejected_at_conversion(self):
        with self.assertRaises(ValueError):
            convert_hook_attack_types({'mMin': '1', 'mMax': '1', 'mDamage': '-inf'})


class ParserToStateIntegrationTests(unittest.TestCase):
    """Integration: capture_log_parser output → assemble_hook_attacks → normalise_attack → choose_attack.

    The capture_log_parser (automation/capture_log_parser.py) emits ParsedRecord objects
    whose .fields dict uses structured tuple keys:
        ('ATTACK', owner, atk_key, field_name) → value_string

    Per-attack sub-fields are NOT grouped into per-attack dicts by the parser itself —
    the parser accumulates all ATTACK rows into a flat dict keyed by these tuples.
    There is no parser-level step that collects mMin/mMax/mDamage etc. for a given
    atk_key into a single dict; that grouping is left to the caller.

    Therefore this test operates at the boundary that IS wired: it receives
    already-grouped attack field dicts (as a caller of the parser would assemble them
    after iterating ParsedRecord.fields) and passes them through
    assemble_hook_attacks → normalise_attack → choose_attack.

    A future test can exercise parse_sim_log end-to-end once a grouping helper
    is added that converts ParsedRecord.fields into per-attack dicts.
    """

    def _group_attack_fields(self, fields: dict, owner: str, atk_key: str) -> dict:
        """Extract a single attack's fields from a ParsedRecord.fields dict.

        Collects all entries whose key matches ('ATTACK', owner, atk_key, field_name)
        and returns {field_name: value_string}.
        """
        result = {}
        for k, v in fields.items():
            if (isinstance(k, tuple) and len(k) == 4
                    and k[0] == 'ATTACK' and k[1] == owner and k[2] == atk_key):
                result[k[3]] = v
        return result

    def test_already_performed_true_excludes_attack_via_assemble(self):
        """already_performed=True from grouped parser output must exclude the attack."""
        # Simulate what a caller would assemble from ParsedRecord.fields after
        # calling parse_sim_log and grouping per-attack fields by atk_key.
        raw_attack = {
            'mMin': '1',
            'mMax': '5',
            'mDamage': '2.0',
            'mAlreadyPerformed': 'true',
            'mRateCounter': '2',
            'mState': '0',
        }
        typed = assemble_hook_attacks([raw_attack])
        canonical = normalise_attack(typed[0])
        result = choose_attack([canonical], [2], None)
        self.assertIsNone(result)

    def test_already_performed_false_includes_attack_via_assemble(self):
        """already_performed=False from grouped parser output must keep the attack eligible."""
        raw_attack = {
            'mMin': '1',
            'mMax': '5',
            'mDamage': '2.0',
            'mAlreadyPerformed': 'false',
            'mRateCounter': '2',
            'mState': '0',
        }
        typed = assemble_hook_attacks([raw_attack])
        canonical = normalise_attack(typed[0])
        # counter=2 >= min=1 → eligible
        result = choose_attack([canonical], [2], lambda label: 0)
        self.assertEqual(result, 0)

    def test_parse_sim_log_produces_grouped_fields_for_attack(self):
        """parse_sim_log recovers ATTACK rows; grouping by atk_key yields the raw dict."""
        from capture_log_parser import parse_sim_log, partition_sim_log

        # Construct minimal log lines for one complete sim block with one attack entry.
        log_lines = [
            'AUTOMATION_SIM_BEGIN=1|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mMin|1|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mMax|5|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mDamage|2.0|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mAlreadyPerformed|true|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mRateCounter|2|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mState|0|E',
            'AUTOMATION_SIM_END=1|E',
        ]
        records = parse_sim_log(log_lines)
        good, _ = partition_sim_log(records)
        self.assertEqual(len(good), 1)

        # Group attack fields for owner='enemy', atk_key='0'
        raw_attack = self._group_attack_fields(good[0].fields, 'enemy', '0')
        self.assertEqual(raw_attack.get('mMin'), '1')
        self.assertEqual(raw_attack.get('mMax'), '5')
        self.assertEqual(raw_attack.get('mDamage'), '2.0')
        self.assertEqual(raw_attack.get('mAlreadyPerformed'), 'true')

        # Full pipeline: grouped fields → assemble → normalise → choose_attack
        typed = assemble_hook_attacks([raw_attack])
        canonical = normalise_attack(typed[0])
        # already_performed=True → no attack chosen
        result = choose_attack([canonical], [2], None)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
