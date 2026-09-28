import unittest

from native_enemy_ai import (
    UrgencyLevel,
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


if __name__ == '__main__':
    unittest.main()
