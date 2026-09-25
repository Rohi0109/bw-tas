"""Identified nonlethal attacks from the September 11 native trace.

Unlike kill-only observations these retain the actual quarter-heart damage.
Boards below are synthetic rearrangements of the same plain selected letters;
there are no path-dependent powers in these five captures.
"""

import unittest

from deluxe_optimizer import DAMAGE_BY_LENGTH, adjusted_word_length, candidates, damage_for
from test_deluxe_optimizer import state


class NativeDamageRegressions(unittest.TestCase):
    def test_captured_native_damage_table(self):
        captured = [.25, .25, .5, .75, 1, 1.5, 2, 2.75,
                    3.5, 4.5, 5.5, 6.75, 8, 9.5, 11, 13]
        self.assertEqual([DAMAGE_BY_LENGTH[tier] for tier in range(1, 17)], captured)

    def test_five_identified_nonlethal_attacks(self):
        captures = [
            # attack ID, word, offense, native tier, native full damage, HP loss
            (10, 'UPBINDS', 0.0, 8, 2.75, 2.75),
            (14, 'TRIFORIUM', .089673914015293, 10, 4.9035326130688, 4.75),
            (20, 'WEEVILY', .17119565606117, 10, 5.2703804522753, 5.25),
            (22, 'WHUMPED', .29619565606117, 8, 3.5645380541682, 3.5),
            (30, 'DEVELOPED', .39619570970535, 10, 6.2828806936741, 6.25),
        ]
        for identifier, word, offense, tier, native_full, hp_loss in captures:
            with self.subTest(attack_id=identifier, word=word):
                letters = word.ljust(16, 'A')
                current = state(board='/'.join(letters[i:i+4] for i in range(0, 16, 4)),
                                offense=offense, treasures=frozenset({'bow of zyx'}))
                path = tuple(range(len(word)))
                self.assertEqual(adjusted_word_length(current, word, path), tier)
                self.assertAlmostEqual(DAMAGE_BY_LENGTH[tier]*(1+offense), native_full)
                self.assertEqual(damage_for(current, word, path, frozenset()), hp_loss)

    def test_bow_assigns_xyz_weights_and_does_not_affect_plain_letters(self):
        bow = state(treasures=frozenset({'bow of zyx'}))
        plain = state()
        self.assertEqual(adjusted_word_length(bow, 'ANALYZER', tuple(range(8))), 11)
        self.assertEqual(adjusted_word_length(plain, 'ANALYZER', tuple(range(8))), 10)
        self.assertEqual(adjusted_word_length(bow, 'BAPTISE', tuple(range(7))), 8)

    def test_tier_clamp_does_not_admit_short_dictionary_words(self):
        self.assertEqual(adjusted_word_length(state(), 'Z'*16, tuple(range(16))), 16)
        self.assertEqual(candidates(state(), ['', 'A', 'AA'], frozenset(), .01), [])

    def test_all_suppressed_tiles_have_no_base_damage(self):
        current = state(zero_damage=(True,)*16)
        self.assertEqual(damage_for(current, 'TEST', (0, 1, 2, 3), frozenset()), 0)
