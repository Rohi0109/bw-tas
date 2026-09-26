import unittest
from dataclasses import replace

from combat_models import DeluxeState
from scenario_simulator import simulate


def initial():
    return DeluxeState(sequence=1, board='TEST/ABCD/EFGH/IJKL',
                       gems=('none',)*16, tile_powers=(0.,)*16,
                       book=1, chapter=1, stage=1, enemy='Passive target',
                       hp=1.5, max_hp=1.5, offense=0,
                       treasures=frozenset(), overkill_thresholds=(0, 1, 2, 3))


class ScenarioTests(unittest.TestCase):
    def test_multiturn_consumes_stream_and_preserves_initial_state(self):
        state = initial()
        report = simulate(state, ['TEST'], 'TESTTEST', 'shortest-lethal')
        self.assertEqual(report['status'], 'target-defeated')
        self.assertEqual(len(report['attacks']), 2)
        self.assertEqual(report['refill_letters_consumed'], 4)
        self.assertEqual(state.hp, 1.5)
        self.assertFalse(report['terminal_board_resolved'])

    def test_unknown_refill_does_not_fabricate_successor(self):
        report = simulate(initial(), ['TEST'], 'AAA', 'max-damage')
        self.assertEqual(report['status'], 'refill-exhausted')
        self.assertEqual(report['attacks'], [])
        self.assertEqual(report['final_state']['hp'], 1.5)

    def test_branches_replay_independently(self):
        first = simulate(initial(), ['TEST'], 'TEST', 'max-damage')
        simulate(initial(), ['TEST'], 'ABCD', 'shortest-lethal')
        self.assertEqual(first, simulate(initial(), ['TEST'], 'TEST', 'max-damage'))

    def test_no_word_and_attack_limit_are_not_victories(self):
        self.assertEqual(simulate(initial(), ['ZZZ'], '', 'max-damage')['status'],
                         'no-playable-word')
        self.assertEqual(simulate(initial(), ['TEST'], 'TEST', 'max-damage',
                                  max_attacks=1)['status'], 'attack-limit')

    def test_unsupported_state_rejected(self):
        for changes in [dict(player_frozen=True), dict(player_damage_multiplier=2),
                        dict(gems=('ruby',)*16), dict(treasures=frozenset({'hammer'})),
                        dict(hp=float('nan')), dict(board='bad')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                simulate(replace(initial(), **changes), ['TEST'], 'TEST', 'max-damage')


if __name__ == '__main__':
    unittest.main()
