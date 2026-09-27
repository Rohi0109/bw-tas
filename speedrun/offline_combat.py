"""Seeded plain-tile encounters with explicit hypothetical scheduling.

No native enemy AI, effects, timing, rewards or shared cosmetic RNG scheduling.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
import re

from deluxe_optimizer import LETTER_BONUSES
from native_damage_model import word_damage, quarter_hp_loss
from native_letter_picker import pick_letter
from native_rng import NativeRng, NativeRngState
from simulate_transitions import compact_board

MODEL = 'seeded-plain-combat-v1'


def validate(state):
    if state.get('model') != MODEL:
        raise ValueError(f'Explicit model {MODEL} required')
    if not re.fullmatch(r'[A-Z]{4}(?:/[A-Z]{4}){3}', state['board']):
        raise ValueError('Expected plain 4x4 uppercase board')
    for key in ('player_hp', 'enemy_hp', 'enemy_attack', 'offense'):
        value = state[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'Invalid {key}')
    if not state['words'] or any(not re.fullmatch('[A-Z]{3,16}', w) for w in state['words']):
        raise ValueError('Supply uppercase tile-word allowlist; Q denotes QU')
    if any(not re.fullmatch('[A-Z]{3,4}', w) for w in state['exclusions']):
        raise ValueError('Invalid exclusion table')
    if type(state['turn']) is not int or state['turn'] < 0:
        raise ValueError('Invalid turn counter')
    if set(state) != {'model', 'board', 'player_hp', 'enemy_hp', 'enemy_attack',
                      'offense', 'words', 'exclusions', 'turn', 'rng'}:
        raise ValueError('Unknown state fields; gems/statuses/treasures are unsupported')
    rng = NativeRng()
    rng.restore(NativeRngState(**state['rng']))


def create(scenario):
    allowed = {'model', 'board', 'player_hp', 'enemy_hp', 'enemy_attack',
               'offense', 'words', 'exclusions', 'seed'}
    if set(scenario) != allowed or type(scenario['seed']) is not int:
        raise ValueError('Scenario requires exact documented fields and integer seed')
    state = deepcopy(scenario)
    rng = NativeRng(state.pop('seed')).snapshot()
    state.update(turn=0, rng=dict(words=list(rng.words), cursor=rng.cursor))
    validate(state)
    return state


def terminal(state):
    if state['player_hp'] == 0:
        return 'player-defeated'
    if state['enemy_hp'] == 0:
        return 'enemy-defeated'
    return None


def path_for(board, word):
    available = list(board.replace('/', ''))
    path = []
    for letter in word:
        if letter not in available:
            return None
        index = available.index(letter)
        available[index] = None
        path.append(index)
    return path


def damage(word, offense):
    return word_damage([1 + LETTER_BONUSES.get(c, 0) for c in word],
                       ['none'] * len(word), offense=offense)


def step(checkpoint, word):
    """Pure transition; failed actions leave caller state and RNG untouched."""
    validate(checkpoint)
    if terminal(checkpoint):
        raise ValueError('Encounter has ended')
    path = path_for(checkpoint['board'], word)
    if word not in checkpoint['words'] or path is None:
        raise ValueError('Word is not legal on this rack')
    state = deepcopy(checkpoint)
    rng = NativeRng()
    rng.restore(NativeRngState(**state['rng']))
    breakdown = damage(word, state['offense'])
    loss = min(state['enemy_hp'], quarter_hp_loss(breakdown.full))
    state['enemy_hp'] -= loss
    state['turn'] += 1
    events = [dict(kind='word-damage', word=word, path=path,
                   breakdown=asdict(breakdown), hp_loss=loss)]
    # A lethal word ends the encounter before hypothetical refill/retaliation.
    if state['enemy_hp'] > 0:
        compacted = compact_board(state['board'], path, '*' * len(path))
        board = compacted['board']
        for slot in compacted['replacement_slots']:
            pick = pick_letter(board, rng, state['exclusions'], [0]*26,
                               restrict_duplicates=False)
            letters = list(board.replace('/', ''))
            letters[slot] = pick['letter']
            board = '/'.join(''.join(letters[i:i+4]) for i in range(0, 16, 4))
            events.append(dict(kind='refill', slot=slot, **pick))
        state['board'] = board
        retaliation = min(state['player_hp'], quarter_hp_loss(state['enemy_attack']))
        state['player_hp'] -= retaliation
        events.append(dict(kind='scripted-retaliation', hp_loss=retaliation))
    snapshot = rng.snapshot()
    state['rng'] = dict(words=list(snapshot.words), cursor=snapshot.cursor)
    return state, events


def simulate(checkpoint, strategy='max-damage', max_turns=100):
    validate(checkpoint)
    if strategy not in ('max-damage', 'shortest-lethal') or type(max_turns) is not int or max_turns < 1:
        raise ValueError('Invalid strategy or turn limit')
    state = deepcopy(checkpoint)
    trace = []
    while not terminal(state) and len(trace) < max_turns:
        options = [(word, quarter_hp_loss(damage(word, state['offense']).full))
                   for word in sorted(set(state['words'])) if path_for(state['board'], word) is not None]
        if not options:
            break
        lethal = [pair for pair in options if pair[1] >= state['enemy_hp']]
        if strategy == 'shortest-lethal' and lethal:
            word, _ = min(lethal, key=lambda pair: (len(pair[0]), pair[0]))
        else:
            word, _ = min(options, key=lambda pair: (-pair[1], len(pair[0]), pair[0]))
        state, events = step(state, word)
        trace.append(dict(turn=state['turn'], events=events, board=state['board'],
                          player_hp=state['player_hp'], enemy_hp=state['enemy_hp']))
    status = terminal(state) or ('turn-limit' if len(trace) == max_turns else 'no-playable-word')
    return dict(model=MODEL, strategy=strategy, status=status, trace=trace,
                checkpoint=state, terminal_board_resolved=status != 'enemy-defeated',
                assumptions=[
                    'Plain tiles, supplied word allowlist; no treasures or status effects.',
                    'Column-major refill with one engine draw per tile and zero extra frequencies.',
                    'Exclusions supplied by scenario; empty list is synthetic, not native parity.',
                    'Constant scripted retaliation follows refill; native AI/order not reproduced.',
                    'Lethal attack stops before refill/rewards; terminal board is unresolved.',
                    'No native timing or campaign progression is simulated.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--resume', action='store_true', help='input is a saved report')
    parser.add_argument('--strategy', choices=['max-damage', 'shortest-lethal'], default='max-damage')
    parser.add_argument('--max-turns', type=int, default=100)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.input.read_text())
    state = source['checkpoint'] if args.resume else create(source)
    report = simulate(state, args.strategy, args.max_turns)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(report['status'], len(report['trace']), 'turns')


if __name__ == '__main__':
    main()
