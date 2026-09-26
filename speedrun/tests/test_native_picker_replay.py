import unittest

from native_picker_replay import replay
from native_rng import NativeRng, NativeRngState


class PickerReplayTests(unittest.TestCase):
    def pick(self, **overrides):
        return dict(kind='pick', board='****/****/****/****',
                    extras=[0]*26, restrict_duplicates=False, **overrides)

    def test_interleaving_and_checkpoint_resume(self):
        initial = NativeRng(123).snapshot()
        events = [self.pick(), dict(kind='draws', count=625), self.pick()]
        whole = replay(initial, events, ())
        prefix = replay(initial, events[:2], ())
        checkpoint = NativeRngState(**prefix['final_rng'])
        suffix = replay(checkpoint, events[2:], ())
        self.assertEqual(whole['final_rng'], suffix['final_rng'])
        self.assertEqual(whole['events'][-1]['letter'], suffix['events'][0]['letter'])
        oracle = NativeRng(123)
        draws = [oracle.next_rand() for _ in range(627)]
        self.assertEqual(whole['events'][1]['draws'], draws[1:626])
        self.assertEqual(whole['events'][-1]['draw'], draws[-1])
        self.assertEqual(initial, NativeRng(123).snapshot())

    def test_mismatch_does_not_change_prediction(self):
        initial = NativeRng(42).snapshot()
        baseline = replay(initial, [self.pick()], ())
        wrong = (baseline['events'][0]['draw'] + 1) & 0x7fffffff
        result = replay(initial, [self.pick(expected_draw=wrong)], ())
        self.assertEqual(result['mismatch_count'], 1)
        self.assertEqual(result['final_rng'], baseline['final_rng'])

    def test_invalid_schedule_leaves_source_unchanged(self):
        rng = NativeRng(9)
        initial = rng.snapshot()
        for invalid in [dict(kind='draws', count=-1), dict(kind='guess-refill'),
                        dict(kind='draws', count=True), self.pick(expected_letter='QU')]:
            with self.assertRaises(ValueError):
                replay(initial, [self.pick(), invalid], ())
            self.assertEqual(rng.snapshot(), initial)


if __name__ == '__main__':
    unittest.main()
