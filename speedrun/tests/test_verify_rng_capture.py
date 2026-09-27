from copy import deepcopy
import unittest

from native_rng import NativeRng
from verify_rng_capture import verify


def trace():
    rng = NativeRng(123)
    rows = [dict(kind='header', schema_version=1, build={'fixture': 'synthetic'})]
    for index in range(3):
        before = rng.snapshot()._asdict()
        value = rng.next_rand()
        rows.append(dict(kind='draw', index=index+1, before=before, value=value,
                         after=rng.snapshot()._asdict()))
    rows.append(dict(kind='end', complete=True, draws=3, pending=False, error=None))
    return rows


class CaptureVerifierTests(unittest.TestCase):
    def test_complete_and_truncated(self):
        self.assertEqual(verify(trace())['status'], 'match')
        self.assertEqual(verify(trace()[:-1])['status'], 'incomplete')

    def test_first_value_divergence(self):
        rows = trace()
        rows[2]['value'] ^= 1
        result = verify(rows)
        self.assertEqual((result['status'],result['draw'],result['field']), ('diverged',2,'value'))

    def test_uncaptured_state_change_is_not_silently_restored(self):
        rows = deepcopy(trace())
        rows[2]['before'] = NativeRng(9).snapshot()._asdict()
        self.assertEqual(verify(rows)['field'], 'before-state')

    def test_missing_draw_and_extra_records_rejected(self):
        rows = trace()
        del rows[2]
        with self.assertRaises(ValueError): verify(rows)
        with self.assertRaises(ValueError): verify(trace()+[{}])


if __name__ == '__main__':
    unittest.main()
