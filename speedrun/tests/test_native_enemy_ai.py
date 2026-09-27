import unittest

from native_enemy_ai import (
    UrgencyLevel,
    choose_attack,
    get_urgency,
    urgency_weight,
    tick_counters,
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
        # Single eligible: no draw consumed regardless of draw=None.
        attacks = [atk(min=0, max=5)]
        self.assertEqual(choose_attack(attacks, [2], None), 0)

    def test_no_eligible_attacks_returns_none(self):
        attacks = [atk(min=5, max=10)]
        self.assertIsNone(choose_attack(attacks, [2], None))

    def test_inactive_attack_not_eligible(self):
        attacks = [atk(min=0, max=5, state='inactive'), atk(min=0, max=5)]
        self.assertEqual(choose_attack(attacks, [3, 3], None), 1)

    def test_already_performed_not_eligible(self):
        attacks = [atk(min=0, max=5, already_performed=True), atk(min=0, max=5)]
        self.assertEqual(choose_attack(attacks, [3, 3], None), 1)

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


if __name__ == '__main__':
    unittest.main()
