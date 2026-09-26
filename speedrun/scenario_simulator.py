"""Offline plain-rack strategy experiments against a passive target.

Refills are explicit hypothetical inputs, never inferred from another action's
recorded successor. This module does not import or launch an input controller.
"""

import argparse
import json
import math
import re
from dataclasses import replace
from pathlib import Path

from book1_optimizer import candidate_payload, state_from_payload, state_payload
from deluxe_optimizer import candidates, choose
from simulate_transitions import compact_board


STRATEGIES = ('shortest-lethal', 'max-damage')


def validate(state, words, refills, max_attacks, click_delay):
    if not re.fullmatch(r'[A-Z]{4}(?:/[A-Z]{4}){3}', state.board):
        raise ValueError('Expected a 4x4 uppercase board')
    for name in ('gems', 'tile_powers', 'selectable', 'zero_damage'):
        if len(getattr(state, name)) != 16:
            raise ValueError(f'{name} must contain 16 entries')
    if (any(g != 'none' for g in state.gems) or any(state.tile_powers)
            or not all(state.selectable) or any(state.zero_damage)
            or state.player_powered_up or state.player_damage_multiplier != 1
            or state.player_stunned or state.player_frozen or state.player_petrified
            or state.player_has_damage_over_time):
        raise ValueError('Only plain, selectable racks without player effects are supported')
    if state.treasures - {'bow of zyx'}:
        raise ValueError('Only no treasure or Bow of Zyx is supported')
    if (not all(math.isfinite(v) for v in (state.hp, state.max_hp, state.offense, click_delay))
            or not 0 < state.hp <= state.max_hp or state.offense < 0 or click_delay < 0):
        raise ValueError('Invalid HP, offense, or click delay')
    if type(max_attacks) is not int or max_attacks < 1:
        raise ValueError('max_attacks must be a positive integer')
    if not words or any(not re.fullmatch('[A-Z]{3,16}', w) for w in words):
        raise ValueError('Supply an uppercase word allowlist; Q represents one QU tile')
    if not isinstance(refills, str) or not re.fullmatch('[A-Z]*', refills):
        raise ValueError('refill_stream must contain uppercase letters only')


def simulate(state, words, refill_stream, strategy, *, max_attacks=20, click_delay=.01):
    """Run one independent scenario; caller state and refill stream are immutable."""
    validate(state, words, refill_stream, max_attacks, click_delay)
    if strategy not in STRATEGIES:
        raise ValueError(f'Unknown strategy: {strategy}')
    initial = state
    attacks, cursor, elapsed = [], 0, 0.0
    status = 'attack-limit'
    for _ in range(max_attacks):
        options = candidates(state, sorted(set(words)), frozenset(), click_delay)
        if not options:
            status = 'no-playable-word'
            break
        action, _ = choose(options, strategy)
        hp = max(0., state.hp - action.damage)
        # Stop before claiming another READY when required refill is unknown.
        if hp > 0 and cursor + len(action.path) > len(refill_stream):
            status = 'refill-exhausted'
            break
        before = state
        refill = ''
        if hp > 0:
            refill = refill_stream[cursor:cursor + len(action.path)]
            cursor += len(action.path)
            board = compact_board(state.board, action.path, refill)['board']
            state = replace(state, board=board, hp=hp, sequence=state.sequence + 1)
        else:
            state = replace(state, hp=0)
        elapsed += action.predicted_time
        attacks.append(dict(before=state_payload(before), action=candidate_payload(action),
                            refill=refill, after=state_payload(state)))
        if hp == 0:
            status = 'target-defeated'
            break
    return dict(strategy=strategy, status=status, attacks=attacks,
                initial_state=state_payload(initial), final_state=state_payload(state),
                refill_letters_consumed=cursor, attack_time_proxy_seconds=elapsed,
                terminal_board_resolved=status != 'target-defeated')


def compare(scenario):
    if scenario.get('model') != 'passive-plain-rack-v1':
        raise ValueError('Explicit model passive-plain-rack-v1 is required')
    state = state_from_payload(scenario['initial_state'])
    results = [simulate(state, scenario['words'], scenario['refill_stream'], strategy,
                        max_attacks=scenario.get('max_attacks', 20),
                        click_delay=scenario.get('click_delay', .01))
               for strategy in STRATEGIES]
    return dict(schema_version=1, model=scenario['model'], results=results,
                assumptions=[
                    'Passive target: no enemy turns, healing, immunities, or player damage.',
                    'Explicit hypothetical refill stream in column-major insertion order; no native RNG prediction.',
                    'Allowlist words are supplied by the caller; dictionary membership is not independently checked.',
                    'Damage and animation estimates reuse the solver; timing excludes enemy turns, navigation, and loading.',
                    'Lethal attacks terminate before refill, rewards, or the next encounter; terminal board is unresolved.',
                    'Scenario rankings are not validated native routes or measured speedups.',
                ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(json.loads(args.scenario.read_text()))
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    for result in report['results']:
        print(result['strategy'], result['status'], len(result['attacks']),
              f"{result['attack_time_proxy_seconds']:.3f}s attack-time proxy")


if __name__ == '__main__':
    main()
