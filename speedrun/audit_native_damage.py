"""Audit a single Lua-runtime log using submission IDs, without guessing gem paths."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from deluxe_optimizer import adjusted_word_length, damage_for, parse_state

ATTACK = re.compile(r'AUTOMATION_ATTACK_ID=(\d+)\|([^|]+)\|([^|]+)\|E')
VALUE = re.compile(r'AUTOMATION_NATIVE_WORD_VALUE=([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|E')
HP = re.compile(r'AUTOMATION_ATTACK_HP=(\d+)\|([^|]+)\|([^|]+)\|E')
TRACE = re.compile(r'AUTOMATION_DAMAGE_TRACE=(\d+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|E')
TABLE = re.compile(r'AUTOMATION_DAMAGE_TABLE=(\d+)\|([^|]+)\|E')


def audit_text(text):
    records = {}
    active = None
    state = None
    buffer = ''
    for number, line in enumerate(text.splitlines(), 1):
        buffer = (buffer + '\n' + line)[-32768:]
        if 'AUTOMATION_READY_SEQ=' in line:
            state = parse_state(buffer)
        match = ATTACK.search(line)
        if match:
            identifier, enemy, word = match.groups()
            active = None
            if identifier in records:
                previous = records[identifier]
                if (enemy, word) != (previous['enemy'], previous['word']):
                    raise ValueError('Conflicting attack ID: split logs by Lua runtime first')
                # Wine console redraws can repeat entire blocks of old events.
                continue
            active = dict(attack_id=int(identifier), source_line=number,
                          enemy=enemy, word=word, hp_events=[], issues=[])
            records[identifier] = active
            if state is None or state.enemy != enemy:
                active['issues'].append('missing-matching-before-state')
                continue
            active.update(sequence=state.sequence, before_hp=state.hp,
                          treasures=sorted(state.treasures), offense=state.offense)
            # Native SubmitTiles spells QU; the solver/rack uses one Q tile.
            modeled_word = word.replace('QU', 'Q')
            active['modeled_word'] = modeled_word
            letters = list(state.board.replace('/', ''))
            path = []
            for letter in modeled_word:
                if letter not in letters:
                    break
                index = letters.index(letter)
                letters[index] = '?'
                path.append(index)
            if len(path) != len(modeled_word):
                active['issues'].append('word-not-on-before-rack')
                continue
            # No native path is logged. Restrict damage checks to boards where
            # tile allocation cannot change the result of the existing model.
            if any(state.zero_damage):
                active['issues'].append('unobserved-zero-damage-tile-path')
                continue
            active['modeled_tier'] = adjusted_word_length(state, modeled_word, tuple(path))
            if (any(state.tile_powers) or state.player_damage_multiplier != 1
                    or 'hand of hercules' in state.treasures):
                active['issues'].append('damage-outside-plain-rack-scope')
                continue
            active['modeled_damage'] = damage_for(state, modeled_word, tuple(path), frozenset())
        match = VALUE.search(line)
        if match and active is not None:
            word, value, tier, enemy = match.groups()
            if (word, enemy) == (active['word'], active['enemy']):
                active['native_value'] = float(value)
                active['native_tier'] = int(tier)
        match = HP.search(line)
        if match and active is not None and int(match[1]) == active['attack_id']:
            active['hp_events'].append([float(match[2]), float(match[3])])
        match = TRACE.search(line)
        if match and active is not None and int(match[1]) == active['attack_id']:
            active['pre_submit_trace'] = dict(
                value=float(match[2]), tier=int(match[3]), base=float(match[4]),
                full_value=float(match[5]), offense=float(match[6]),
                selected_slots=[int(i) for i in match[7].split(',')])
        match = TABLE.search(line)
        if match and active is not None and int(match[1]) == active['attack_id']:
            active['native_damage_table'] = [None if v == 'nil' else float(v)
                                             for v in match[2].split(',')]
    for row in records.values():
        if 'native_tier' in row and 'modeled_tier' in row:
            row['tier_matches'] = row['native_tier'] == row['modeled_tier']
        if 'pre_submit_trace' in row:
            trace = row['pre_submit_trace']
            if 'modeled_tier' in row:
                row['pre_submit_tier_matches'] = trace['tier'] == row['modeled_tier']
            if 'native_value' in row:
                row['value_changed_after_submission'] = trace['value'] != row['native_value']
        if row['hp_events'] and 'modeled_damage' in row:
            old, new = row['hp_events'][0]
            if old != row['before_hp']:
                row['issues'].append('hp-changed-before-first-observed-edge')
                continue
            row['predicted_hp'] = max(0, old-row['modeled_damage'])
            row['hp_matches'] = abs(row['predicted_hp']-new) < 1e-9
            row['nonlethal_damage_check'] = 0 < new < old
            row['first_observed_hp_loss'] = old-new
    return list(records.values())


def audit(source, output):
    raw = source.read_bytes()
    rows = audit_text(raw.decode(errors='replace'))
    counts = Counter(attacks=len(rows))
    for row in rows:
        for field in ('tier_matches', 'hp_matches'):
            if field in row:
                counts[field + ('_yes' if row[field] else '_no')] += 1
        if row.get('nonlethal_damage_check'):
            counts['nonlethal_checks'] += 1
            counts['nonlethal_matches'] += int(row['hp_matches'])
    report = dict(source=str(source.resolve()), source_sha256=hashlib.sha256(raw).hexdigest(),
                  counts=dict(counts), attacks=rows,
                  limitations=['One Lua runtime only; IDs are not globally unique.',
                               'Word-value event is ordered after submission but lacks its own ID.',
                               'HP events can include DOT and healing; first edge is not a damage-component trace.',
                               'Lethal HP is clipped: a match does not validate exact damage.',
                               'Gem/path-dependent damage is excluded; no live scoring changes.'])
    output.mkdir(parents=True, exist_ok=False)
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('runtime/deluxe-modded/lua.log'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.source, args.output)['counts'], indent=2))
