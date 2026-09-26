import unittest
from unittest.mock import patch
import io
import json

from local_worker import context_files, run, validate_result


class LocalWorkerTests(unittest.TestCase):
    def test_reject_invalid_schema(self):
        for content in ('{}', '[]', 'not json', '{"summary":1,"proposal":"x","uncertainties":""}'):
            with self.assertRaises(ValueError):
                validate_result(content)

    def test_reject_outside_repository(self):
        with self.assertRaises(ValueError):
            context_files(['/etc/passwd'])

    def test_truncation_never_accepted(self):
        raw = dict(done=True, done_reason='length', message=dict(content=json.dumps(
            dict(summary='ok', proposal='code', uncertainties=''))))
        with patch('local_worker.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(raw).encode())):
            result = run('test', [], 'test-model', 20, 5)
        self.assertEqual(result['status'], 'invalid')
        self.assertEqual(result['raw'], raw)

    def test_valid_output_still_needs_review(self):
        raw = dict(done=True, done_reason='stop', message=dict(content=json.dumps(
            dict(summary='ok', proposal='code', uncertainties=''))))
        with patch('local_worker.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(raw).encode())) as call:
            result = run('test', [], 'test-model', 20, 5)
        self.assertEqual(result['status'], 'needs-review')
        payload = json.loads(call.call_args.args[0].data)
        self.assertEqual(payload['model'], 'test-model')
        self.assertEqual(payload['options']['num_predict'], 20)


if __name__ == '__main__':
    unittest.main()
