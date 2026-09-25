import copy
import json
import tempfile
import unittest
from pathlib import Path

from book1_optimizer import state_payload
from simulate_transitions import compact_board
from state_graph import build_graph
from test_deluxe_optimizer import state


class GraphTests(unittest.TestCase):
    def row(self, run='a', replacements='AAAA'):
        before = state_payload(state(board='TEST/AAAA/AAAA/AAAA', hp=5))
        after = copy.deepcopy(before)
        after.update(sequence=2, hp=4, board=compact_board(
            before['board'], [0, 1, 2, 3], list(replacements))['board'])
        return dict(run_id=run, book=1, chapter=1, before=before, after=after,
                    action=dict(word='TEST', path=[0, 1, 2, 3]), clean=True,
                    timing=dict(ready_seconds=3, input_seconds=.2, input_attempts=1),
                    native_attack_events=['AUTOMATION_ATTACK_ID=1|Trojan Spearman|TEST|E'])

    def graph(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'rows.jsonl'
            path.write_text('\n'.join(json.dumps(row) for row in rows))
            return build_graph(path)

    def test_repeated_runs_are_evidence_not_proof(self):
        graph = self.graph([self.row(), self.row('b')])
        edge = next(iter(graph['edges'].values()))
        self.assertEqual(edge['status'], 'repeated-observation')
        self.assertFalse(edge['deterministic_verified'])

    def test_conflicts_preserve_both_successors(self):
        graph = self.graph([self.row(), self.row('b', 'ABCD')])
        edge = next(iter(graph['edges'].values()))
        self.assertEqual(edge['status'], 'conflicting-successors')
        self.assertEqual(len(edge['outcomes']), 2)

    def test_duplicates_do_not_count_as_repeats(self):
        graph = self.graph([self.row(), self.row()])
        self.assertEqual(graph['summary']['rejected']['duplicate-observation'], 1)
        self.assertEqual(next(iter(graph['edges'].values()))['independent_runs'], 1)

    def test_exact_tile_order_creates_distinct_actions(self):
        a = self.row()
        a['before']['board'] = 'AAAA/AAAA/AAAA/AAAA'
        a['action']['word'] = 'AAAA'
        a['native_attack_events'] = ['AUTOMATION_ATTACK_ID=1|Trojan Spearman|AAAA|E']
        b = copy.deepcopy(a)
        b['action']['path'] = [3, 2, 1, 0]
        self.assertEqual(self.graph([a, b])['summary']['edges'], 2)

    def test_retry_and_wrong_submission_are_excluded(self):
        a, b = self.row(), self.row('b')
        a['timing']['input_attempts'] = 2
        b['native_attack_events'] = []
        self.assertEqual(self.graph([a, b])['summary']['edges'], 0)
