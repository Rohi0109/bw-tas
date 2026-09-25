import copy
import unittest

from compare_rng_trials import compare
from test_state_graph import GraphTests


class ResetTrialTests(unittest.TestCase):
    def row(self, run):
        row = GraphTests().row(run)
        row['native_attack_events'].append('AUTOMATION_RNG_RESET=1|1|submit|E')
        return row

    def test_three_sessions_agree(self):
        result = compare([self.row(run) for run in ['a', 'b', 'c']])
        self.assertEqual(result['groups'][0]['status'], 'three-session-agreement')

    def test_duplicate_is_not_independent(self):
        row = self.row('a')
        self.assertEqual(compare([row, row, row])['groups'][0]['sessions'], 1)

    def test_rack_divergence_is_reported(self):
        a, b = self.row('a'), self.row('b')
        b['after']['board'] = 'BBBB/AAAA/AAAA/AAAA'
        self.assertEqual(compare([a, b])['groups'][0]['status'], 'diverged')

    def test_wrong_attack_reset_is_excluded(self):
        row = self.row('a')
        row['native_attack_events'][-1] = 'AUTOMATION_RNG_RESET=2|1|submit|E'
        self.assertFalse(compare([row])['groups'])

    def test_seed_policies_are_separate(self):
        a, b = self.row('a'), self.row('b')
        b['native_attack_events'][-1] = 'AUTOMATION_RNG_RESET=1|2|submit|E'
        self.assertEqual(len(compare([a, b])['groups']), 2)

    def test_engine_and_crt_resets_are_not_mixed(self):
        a, b = self.row('a'), self.row('b')
        b['native_attack_events'][-1] = 'AUTOMATION_RNG_RESET=1|1|submit|engine|E'
        groups = compare([a, b])['groups']
        self.assertEqual({g['rng_stream'] for g in groups}, {'crt', 'engine'})
        self.assertTrue(all(g['sessions'] == 1 for g in groups))
