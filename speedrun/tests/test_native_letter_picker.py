import unittest

from native_letter_picker import adjusted_weights, select_letter, eligible_letters, pick_letter
from native_rng import NativeRng


class PickerTests(unittest.TestCase):
    def test_counts_vowel_quota_and_y(self):
        self.assertNotIn('A', eligible_letters('AAAA/BCDF/GHJK/LMN*', []))
        self.assertFalse(set('AEIOUY') & set(eligible_letters('AEIO/UYAE/IOBC/DFG*', [])))

    def test_exclusion_only_checks_patterns_with_holes(self):
        self.assertNotIn('T', eligible_letters('TES*/ABCD/EFGH/IJKL', ['TEST']))
        self.assertIn('T', eligible_letters('TEST/AEIO/UYAB/FGH*', ['TEST']))

    def test_picker_restore_and_input_validation_before_draw(self):
        rng = NativeRng(1)
        checkpoint = rng.snapshot()
        first = pick_letter('TES*/ABCD/EFGH/IJKL', rng, ['TEST'], [0]*26)
        self.assertNotEqual(first['letter'], 'T')
        rng.restore(checkpoint)
        self.assertEqual(first, pick_letter('TES*/ABCD/EFGH/IJKL', rng, ['TEST'], [0]*26))
        checkpoint = rng.snapshot()
        with self.assertRaises(ValueError):
            pick_letter('bad', rng, [], [0]*26)
        self.assertEqual(checkpoint, rng.snapshot())

    def test_duplicate_penalties_and_flag(self):
        counts = [0]*26
        counts[0] = counts[1] = 2
        weights = adjusted_weights('AB', counts, [0]*26)
        self.assertEqual(weights, (7850, 1467))
        self.assertEqual(adjusted_weights('AB', counts, [0]*26,
                                         restrict_duplicates=True), (7850, 0))
        counts[0] = 3
        self.assertEqual(adjusted_weights('A', counts, [0]*26), (7065,))

    def test_extras_precede_integer_penalty(self):
        counts, extras = [0]*26, [0]*26
        counts[1], extras[1] = 2, 2
        self.assertEqual(adjusted_weights('B', counts, extras), (1468,))

    def test_modulo_strict_boundary_and_zero_weight(self):
        self.assertEqual([select_letter('ABC', (2, 0, 3), i) for i in range(7)],
                         list('AACCCAA'))

    def test_bad_native_inputs_rejected(self):
        for letters in ('', 'BA', 'AA', 'a', '*'):
            with self.assertRaises(ValueError):
                adjusted_weights(letters, [0]*26, [0]*26)
        with self.assertRaises(ValueError):
            select_letter('A', (0,), 1)
        with self.assertRaises(ValueError):
            select_letter('A', (1,), -1)


if __name__ == '__main__':
    unittest.main()
