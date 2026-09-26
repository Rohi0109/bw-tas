import unittest

from native_damage_model import word_damage, quarter_hp_loss


class DamageStageTests(unittest.TestCase):
    def test_native_nonlethal_stage_fixtures(self):
        # Native tier/full/HP observations from the Sep 11 audit; input scalar
        # represents already-modified tile value, not a new letter-weight test.
        for tier, offense, full, hp_loss in [
            (8, 0., 2.75, 2.75),
            (10, .089673914015293, 4.9035326130688, 4.75),
            (10, .17119565606117, 5.2703804522753, 5.25),
            (8, .29619565606117, 3.5645380541682, 3.5),
            (10, .39619570970535, 6.2828806936741, 6.25),
        ]:
            result = word_damage([tier], ['none'], offense=offense)
            self.assertAlmostEqual(result.full, full)
            self.assertEqual(quarter_hp_loss(result.full), hp_loss)

    def test_gem_bonus_scales_with_base_not_letter_value(self):
        small = word_damage([4], ['emerald'])
        large = word_damage([10], ['emerald'])
        self.assertAlmostEqual(small.raw_bonus, .15)
        self.assertAlmostEqual(large.raw_bonus, .9)
        self.assertEqual(small.full, 1.)
        self.assertEqual(large.full, 5.5)

    def test_bonus_summed_before_quantization_and_offense(self):
        result = word_damage([2, 2], ['emerald', 'emerald'], offense=.1)
        self.assertAlmostEqual(result.raw_bonus, .3)
        self.assertEqual(result.quantized_bonus, .5)
        self.assertAlmostEqual(result.full, 1.325)

    def test_resistance_and_suppression(self):
        result = word_damage([10], ['emerald'], enemy_gem_multipliers={'emerald': 0.})
        self.assertEqual(result.full, 4.5)
        self.assertEqual(word_damage([-1, 0], ['none', 'none']).full, 0)
        self.assertEqual(word_damage([16.5], ['none']).tier, 16)

    def test_bad_inputs(self):
        for values, gems in [([], []), ([1], []), ([float('nan')], ['none']), ([1], ['unknown'])]:
            with self.assertRaises(ValueError):
                word_damage(values, gems)


if __name__ == '__main__':
    unittest.main()
