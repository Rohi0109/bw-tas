import unittest

from native_enemy_ai import (
    UrgencyLevel,
    choose_attack,
    get_urgency,
    tick_counters,
)


def atk(name='A', min=2, max=5, state='active', already_performed=False,
        damage=1.0, rate_counter=0):
    return dict(name=name, min=min, max=max, state=state,
                already_performed=already_performed, damage=damage,
                rate_counter=rate_counter)


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
        # max=0 means no upper bound; HIGH threshold never reached.
        self.assertEqual(get_urgency(atk(min=2, max=0), 100), UrgencyLevel.MEDIUM)

    def test_max_zero_below_min_is_low(self):
        self.assertEqual(get_urgency(atk(min=3, max=0), 2), UrgencyLevel.LOW)

    def test_max_equals_min_at_threshold_is_high(self):
        # max > 0 and counter >= max → HIGH even when max == min
        self.assertEqual(get_urgency(atk(min=3, max=3), 3), UrgencyLevel.HIGH)


class ChooseAttackTests(unittest.TestCase):
    def test_single_eligible_attack_chosen(self):
        attacks = [atk(min=0, max=5)]
        self.assertEqual(choose_attack(attacks, None, [2]), 0)

    def test_no_eligible_attacks_returns_none(self):
        attacks = [atk(min=5, max=10)]
        self.assertIsNone(choose_attack(attacks, None, [2]))

    def test_inactive_attack_not_eligible(self):
        attacks = [atk(min=0, max=5, state='inactive'), atk(min=0, max=5)]
        self.assertEqual(choose_attack(attacks, None, [3, 3]), 1)

    def test_already_performed_not_eligible(self):
        # already_performed=True excludes the attack regardless of counter.
        # Approximation: native semantics unconfirmed; documented in module.
        attacks = [atk(min=0, max=5, already_performed=True), atk(min=0, max=5)]
        self.assertEqual(choose_attack(attacks, None, [3, 3]), 1)

    def test_high_urgency_wins_over_medium(self):
        # Attack 0: counter=2 → MEDIUM (min=2, max=5)
        # Attack 1: counter=5 → HIGH  (min=2, max=5)
        attacks = [atk(min=2, max=5, name='M'), atk(min=2, max=5, name='H')]
        self.assertEqual(choose_attack(attacks, None, [2, 5]), 1)

    def test_tie_same_urgency_lowest_index_wins(self):
        # Both at MEDIUM; index 0 should win (approximation: lowest index).
        attacks = [atk(min=2, max=5, name='A'), atk(min=2, max=5, name='B')]
        self.assertEqual(choose_attack(attacks, None, [3, 3]), 0)

    def test_tie_high_urgency_lowest_index_wins(self):
        attacks = [atk(min=2, max=5, name='A'), atk(min=2, max=5, name='B')]
        self.assertEqual(choose_attack(attacks, None, [5, 5]), 0)

    def test_all_attacks_ineligible_returns_none(self):
        attacks = [atk(min=5, max=10, name='X'), atk(min=8, max=12, name='Y')]
        self.assertIsNone(choose_attack(attacks, None, [0, 0]))

    def test_rng_none_accepted(self):
        # rng=None is valid; tie-breaking does not consume a draw in this impl.
        attacks = [atk(min=0, max=3)]
        self.assertEqual(choose_attack(attacks, None, [1]), 0)

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            choose_attack([atk()], None, [0, 0])


class TickCountersTests(unittest.TestCase):
    def test_all_increment_when_no_active(self):
        result = tick_counters([0, 2, 5], None)
        self.assertEqual(result, [1, 3, 6])

    def test_active_attack_resets_to_zero(self):
        result = tick_counters([3, 1, 7], 1)
        self.assertEqual(result, [4, 0, 8])

    def test_active_index_zero(self):
        result = tick_counters([5, 2], 0)
        self.assertEqual(result, [0, 3])

    def test_active_last_index(self):
        result = tick_counters([1, 2, 3], 2)
        self.assertEqual(result, [2, 3, 0])

    def test_does_not_mutate_input(self):
        original = [1, 2, 3]
        tick_counters(original, 0)
        self.assertEqual(original, [1, 2, 3])

    def test_empty_list(self):
        self.assertEqual(tick_counters([], None), [])


if __name__ == '__main__':
    unittest.main()
