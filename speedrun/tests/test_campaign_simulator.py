from copy import deepcopy
import json
from pathlib import Path
import unittest

from campaign_simulator import create, simulate, step, urgency, choose_attack


class CampaignTests(unittest.TestCase):
    def definition(self):
        return json.loads((Path(__file__).parents[1]/'examples/campaign.json').read_text())

    def test_urgency_and_draw_consumption(self):
        self.assertEqual([urgency(2,4,n) for n in range(6)], [0,0,33,66,100,100])
        attacks = [dict(min=0,max=0), dict(min=2,max=3)]
        draws = []
        def draw(label):
            draws.append(label)
            return 1
        self.assertEqual(choose_attack(attacks,[1,1],draw),0)
        self.assertEqual(draws,[])
        self.assertEqual(choose_attack(attacks,[1,3],draw),1)
        self.assertEqual(draws,['ai-due'])

    def test_checkpoint_resume_and_campaign_rewards(self):
        state = create(self.definition())
        original = deepcopy(state)
        first = simulate(state,1)
        rest = simulate(json.loads(json.dumps(first['checkpoint'])))
        whole = simulate(state)
        self.assertEqual(whole['checkpoint'],rest['checkpoint'])
        self.assertEqual(whole['trace'],first['trace']+rest['trace'])
        self.assertEqual(state,original)
        self.assertEqual(whole['status'],'campaign-complete')
        self.assertEqual(whole['checkpoint']['xp'],3)
        self.assertEqual(whole['checkpoint']['encounter'],2)

    def test_freeze_expires_and_rng_schedule_survives_skipped_turn(self):
        definition = self.definition()
        definition['player_effects'] = [dict(kind='freeze',turns=1,value=0)]
        definition['rng_schedule']['before-player'] = 2
        state = create(definition)
        after, events = step(state)
        self.assertEqual(after['board'],state['board'])
        self.assertEqual(after['player_effects'],[])
        self.assertIn(dict(kind='turn-skipped',target='player'),events)
        self.assertEqual(after['rng_draws'],4) # 2 scheduled + AI + after-enemy

    def test_poison_death_cancels_actions_and_rewards(self):
        definition = self.definition()
        definition['player_effects'] = [dict(kind='poison',turns=1,value=10)]
        state, events = step(create(definition))
        self.assertEqual(state['status'],'player-defeated')
        self.assertEqual(state['xp'],0)
        self.assertFalse(any(e['kind'] in ('word','enemy-attack','refill') for e in events))

    def test_enemy_poison_lethal_cancels_retaliation(self):
        definition = self.definition()
        definition['encounters'][0]['hp'] = 10
        definition['encounters'][0]['effects'] = [dict(kind='poison',turns=1,value=20)]
        state, events = step(create(definition),'TEST')
        self.assertEqual(state['encounter'],1)
        self.assertFalse(any(e['kind']=='enemy-attack' for e in events))

    def test_shield_and_power_and_illegal_action_atomicity(self):
        definition = self.definition()
        definition['player_effects'] = [dict(kind='power',turns=2,value=2)]
        definition['encounters'][0]['hp'] = 10
        definition['encounters'][0]['effects'] = [dict(kind='shield',turns=2,value=.5)]
        initial = create(definition)
        state, events = step(initial,'TEST')
        self.assertEqual(state['enemy_hp'],9.25)
        before = deepcopy(initial)
        with self.assertRaises(ValueError): step(initial,'ZZZZ')
        self.assertEqual(initial,before)

    def test_unknown_effect_rejected(self):
        definition = self.definition()
        definition['player_effects'] = [dict(kind='petrify',turns=1,value=0)]
        with self.assertRaises(ValueError): create(definition)

    def test_corrupt_checkpoint_rejected(self):
        state = create(self.definition())
        state['counters'] = []
        with self.assertRaises(ValueError): simulate(state)


if __name__ == '__main__':
    unittest.main()
