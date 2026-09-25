"""Offline partial turn model. Refill letters are supplied, never predicted."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from book1_optimizer import state_from_payload
from deluxe_optimizer import damage_for, load_metal_words


def compact_board(board, path, replacements):
    letters = board.replace('/', '')
    used = set(path)
    if (len(letters) != 16 or not path or len(used) != len(path)
            or any(type(i) is not int or not 0 <= i < 16 for i in path)):
        raise ValueError('Invalid board/path')
    slots, mapping = [], []
    result = [''] * 16
    for col in range(4):
        column = list(range(col, 16, 4))
        survivors = [i for i in column if i not in used]
        count = 4 - len(survivors)
        slots.extend(column[:count])
        for src, dst in zip(survivors, column[count:]):
            result[dst] = letters[src]
            mapping.append([src, dst])
    if len(replacements) != len(slots) or any(len(c) != 1 for c in replacements):
        raise ValueError('Supply one observed letter per refill slot')
    for slot, letter in zip(slots, replacements):
        result[slot] = letter
    return dict(board='/'.join(''.join(result[i:i+4]) for i in range(0, 16, 4)),
                replacement_slots=slots, survivor_mapping=mapping)


def replay(row, metal_words=frozenset()):
    before, after, action = row['before'], row['after'], row['action']
    state = state_from_payload(before)
    path = tuple(action['path'])
    if ''.join(before['board'].replace('/', '')[i] for i in path) != action['word']:
        raise ValueError('Path does not spell word')
    predicted = compact_board(before['board'], path,
                              row['audit']['refill']['observed_replacement_letters'])
    damage = damage_for(state, action['word'], path, metal_words)
    predicted['damage'] = damage
    predicted['hp'] = max(0, state.hp - damage)
    mismatches = []
    if predicted['board'] != after['board']:
        mismatches.append('board')
    if abs(predicted['hp'] - after['hp']) > 1e-9:
        mismatches.append('enemy-hp')
    status = {k: v for k, v in before.items() if k.startswith('player_')}
    return dict(run_id=row.get('run_id'), source_line=row['audit']['source_line'],
                chapter=row['chapter'], enemy=state.enemy,
                treasures=sorted(state.treasures), status=status,
                word=action['word'], predicted=predicted,
                observed_hp=after['hp'], observed_net_damage=state.hp-after['hp'],
                mismatches=mismatches,
                unsupported=['powered-up-damage'] if state.player_damage_multiplier != 1 else [])


def evaluate(source, output, metal_words=frozenset()):
    output.mkdir(parents=True, exist_ok=False)
    totals = Counter()
    groups = defaultdict(Counter)
    digest = hashlib.sha256()
    with source.open('rb') as stream, (output / 'results.jsonl').open('w') as results:
        for raw in stream:
            digest.update(raw)
            result = replay(json.loads(raw), metal_words)
            counts = Counter(observations=1, board_matches=int('board' not in result['mismatches']),
                             hp_matches=int('enemy-hp' not in result['mismatches']),
                             unsupported=int(bool(result['unsupported'])))
            totals.update(counts)
            key = json.dumps({k: result[k] for k in ('run_id', 'chapter', 'enemy', 'treasures', 'status')}, sort_keys=True)
            groups[key].update(counts)
            results.write(json.dumps(result, sort_keys=True) + '\n')
    report = dict(source=str(source.resolve()), source_sha256=digest.hexdigest(),
                  totals=dict(totals), groups=[dict(context=json.loads(k), counts=dict(v)) for k, v in sorted(groups.items())],
                  limitations=['Board checks reuse observed refills from a gravity-filtered corpus; not independent validation.',
                               'Damage is the existing solver estimate, not a complete enemy/status model.',
                               'No prediction of RNG, gems, status transitions, enemy turns, or animation frames.',
                               'Historical attack causality is unverified; missing run IDs remain unknown.'])
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--metals', type=Path, default=Path('runtime/deluxe-modded/.tas-data/metals.luc'))
    args = parser.parse_args()
    print(json.dumps(evaluate(args.source, args.output, load_metal_words(args.metals))['totals'], indent=2))
