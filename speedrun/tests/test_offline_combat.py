from copy import deepcopy
import json
from pathlib import Path
import unittest

from offline_combat import create, simulate, step


class OfflineCombatTests(unittest.TestCase):
    def initial(self):
        return create(json.loads((Path(__file__).parents[1]/'examples/seeded_combat.json').read_text()))

    def test_checkpoint_resume_equals_uninterrupted(self):
        state = self.initial()
        whole = simulate(state)
        first = simulate(state, max_turns=1)
        checkpoint = json.loads(json.dumps(first['checkpoint']))
        rest = simulate(checkpoint)
        self.assertEqual(whole['checkpoint'], rest['checkpoint'])
        self.assertEqual(whole['trace'], first['trace'] + rest['trace'])
        self.assertEqual(whole['status'], 'enemy-defeated')

    def test_branching_does_not_mutate_checkpoint(self):
        state = self.initial()
        original = deepcopy(state)
        first, events = step(state, 'TEST')
        step(state, 'BAD')
        self.assertEqual(step(state, 'TEST'), (first, events))
        self.assertEqual(state, original)
        self.assertEqual(first['rng']['cursor'], 4)
        self.assertEqual(first['player_hp'], 4.5)
        self.assertEqual(sum(e['kind']=='refill' for e in events), 4)

    def test_lethal_cancels_refill_and_retaliation(self):
        state = self.initial()
        state['enemy_hp'] = .25
        after, events = step(state, 'TEST')
        self.assertEqual(after['rng'], state['rng'])
        self.assertEqual(after['player_hp'], state['player_hp'])
        self.assertEqual(len(events), 1)
        with self.assertRaises(ValueError):
            step(after, 'TEST')

    def test_loss_no_words_and_limits_are_distinct(self):
        state = self.initial()
        state['enemy_hp'] = 100
        state['player_hp'] = .25
        self.assertEqual(simulate(state)['status'], 'player-defeated')
        state = self.initial()
        self.assertEqual(simulate(state, max_turns=1)['status'], 'turn-limit')
        state['words'] = ['ZZZ']
        self.assertEqual(simulate(state)['status'], 'no-playable-word')

    def test_illegal_duplicate_path_and_unknown_mechanics_rejected(self):
        state = self.initial()
        state['words'].append('TTTT')
        before = deepcopy(state)
        with self.assertRaises(ValueError):
            step(state, 'TTTT')
        self.assertEqual(state, before)
        state['gems'] = ['ruby']*16
        with self.assertRaises(ValueError):
            simulate(state)


if __name__ == '__main__':
    unittest.main()
