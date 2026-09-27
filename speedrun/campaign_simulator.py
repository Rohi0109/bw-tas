"""Experimental declarative campaigns; native scheduling parity is not claimed.

Rules are explicit scenario inputs. See CAMPAIGN_SIMULATOR.md for phase order.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path

from native_rng import NativeRng, NativeRngState
from native_damage_model import quarter_hp_loss
from native_letter_picker import pick_letter
from offline_combat import create as create_battle, damage, path_for
from simulate_transitions import compact_board

MODEL = 'declarative-campaign-v1'
PHASES = ('before-player', 'before-refill', 'before-enemy', 'after-enemy', 'encounter')
EFFECTS = ('poison', 'regen', 'stun', 'freeze', 'power', 'shield')


def validate_checkpoint(state):
    required = {'model','definition','board','player_hp','player_max_hp','player_effects',
                'enemy_hp','enemy_effects','counters','encounter','turn','xp','rng',
                'rng_draws','status'}
    if set(state) != required or state['model'] != MODEL:
        raise ValueError('Invalid campaign checkpoint fields')
    validate_definition(state['definition'])
    import re
    if not re.fullmatch(r'[A-Z]{4}(?:/[A-Z]{4}){3}', state['board']):
        raise ValueError('Invalid checkpoint board')
    for key in ('player_hp','player_max_hp','enemy_hp'):
        number(state[key], key)
    if state['player_hp'] > state['player_max_hp']:
        raise ValueError('Player HP exceeds maximum')
    if state['player_max_hp'] != state['definition']['initial']['player_hp']:
        raise ValueError('Checkpoint maximum HP differs from campaign definition')
    for key in ('encounter','turn','xp','rng_draws'):
        integer(state[key], key)
    for owner in ('player','enemy'):
        for effect in state[owner+'_effects']:
            effect_valid(effect)
    count = len(state['definition']['encounters'])
    if state['status'] not in ('running','player-defeated','campaign-complete','no-playable-word'):
        raise ValueError('Invalid campaign status')
    if state['encounter'] > count or (state['encounter'] == count) != (state['status'] == 'campaign-complete'):
        raise ValueError('Invalid campaign boundary')
    if state['status'] == 'campaign-complete' and (state['enemy_hp'] != 0 or state['player_hp'] == 0):
        raise ValueError('Completed campaign requires a surviving player and defeated enemy')
    if state['status'] == 'running' and (state['player_hp'] == 0 or state['enemy_hp'] == 0):
        raise ValueError('Running checkpoint has a defeated combatant')
    if state['status'] == 'player-defeated' and state['player_hp'] != 0:
        raise ValueError('Defeated player must have zero HP')
    enemy = state['definition']['encounters'][min(state['encounter'], count-1)]
    if len(state['counters']) != len(enemy['attacks']) or state['enemy_hp'] > enemy['hp']:
        raise ValueError('Checkpoint does not match encounter')
    expected_xp = sum(e['reward']['xp'] for e in state['definition']['encounters'][:state['encounter']])
    if state['xp'] != expected_xp:
        raise ValueError('Checkpoint XP differs from completed encounter rewards')
    if state['status'] == 'no-playable-word':
        if (state['player_hp'] == 0 or state['enemy_hp'] == 0
                or any(path_for(state['board'], word) is not None
                       for word in state['definition']['initial']['words'])):
            raise ValueError('Checkpoint no-playable-word status contradicts state')
    for counter in state['counters']:
        integer(counter, 'attack counter')
    rng = NativeRng()
    rng.restore(NativeRngState(**state['rng']))
    expected_cursor = (state['rng_draws']-1) % 624 + 1 if state['rng_draws'] else 624
    if rng.snapshot().cursor != expected_cursor:
        raise ValueError('RNG draw count disagrees with checkpoint cursor')


def number(value, name, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'Invalid {name}')


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'Invalid {name}')


def effect_valid(effect):
    if set(effect) != {'kind', 'turns', 'value'} or effect['kind'] not in EFFECTS:
        raise ValueError('Unsupported effect')
    integer(effect['turns'], 'effect duration', 1)
    number(effect['value'], 'effect value')


def validate_definition(definition):
    if set(definition) != {'model', 'initial', 'encounters', 'rng_schedule', 'player_effects'} or definition['model'] != MODEL:
        raise ValueError('Expected declarative-campaign-v1 definition')
    create_battle(definition['initial'])
    if set(definition['rng_schedule']) != set(PHASES):
        raise ValueError('Explicit draw counts required for all phases')
    for count in definition['rng_schedule'].values():
        integer(count, 'scheduled draws')
        if count > 10000:
            raise ValueError('Scheduled draw limit exceeded')
    for effect in definition['player_effects']:
        effect_valid(effect)
    if not definition['encounters']:
        raise ValueError('Empty campaign')
    for enemy in definition['encounters']:
        if set(enemy) != {'name', 'book', 'chapter', 'hp', 'attacks', 'effects', 'reward'}:
            raise ValueError('Unknown encounter fields')
        if not isinstance(enemy['name'], str) or not enemy['name']:
            raise ValueError('Enemy requires name')
        for key in ('book', 'chapter'):
            integer(enemy[key], key, 1)
        number(enemy['hp'], 'enemy hp', .25)
        if set(enemy['reward']) != {'xp', 'heal'}:
            raise ValueError('Only explicit XP/heal rewards supported')
        integer(enemy['reward']['xp'], 'xp')
        number(enemy['reward']['heal'], 'heal')
        for effect in enemy['effects']:
            effect_valid(effect)
        if not enemy['attacks']:
            raise ValueError('Enemy needs at least one attack')
        for attack in enemy['attacks']:
            if set(attack) != {'name', 'min', 'max', 'damage', 'effects'}:
                raise ValueError('Unknown attack fields')
            if not isinstance(attack['name'], str) or not attack['name']:
                raise ValueError('Attack requires name')
            integer(attack['min'], 'attack min')
            if type(attack['max']) is not int or attack['max'] < -1:
                raise ValueError('Invalid attack max')
            number(attack['damage'], 'attack damage')
            for effect in attack['effects']:
                effect_valid(effect)


def urgency(minimum, maximum, counter):
    """Normal turn-based AttackBaseClass GetUrgency (no debug/timed mode)."""
    if counter < minimum:
        return 0
    if maximum == minimum:
        return 100
    if maximum < minimum:
        return 1
    return min(100, max(1, math.floor(100*(counter-minimum+1)/(maximum-minimum+1))))


def choose_attack(attacks, counters, draw):
    weights = [urgency(a['min'], a['max'], n) for a, n in zip(attacks, counters)]
    due = [i for i, w in enumerate(weights) if w >= 100]
    if len(due) == 1:
        return due[0]  # Native chooser consumes no draw for one due attack.
    if due:
        return due[draw('ai-due') % len(due)]
    total = sum(weights)
    if not total:
        return None
    value = draw('ai-weighted') % total
    for i, weight in enumerate(weights):
        if value < weight:
            return i
        value -= weight
    raise AssertionError('Unreachable')


def create(definition):
    validate_definition(definition)
    definition = deepcopy(definition)
    battle = create_battle(definition['initial'])
    state = dict(model=MODEL, definition=definition, board=battle['board'],
                 player_hp=battle['player_hp'], player_max_hp=battle['player_hp'],
                 player_effects=deepcopy(definition['player_effects']),
                 enemy_hp=0, enemy_effects=[], counters=[], encounter=0,
                 turn=0, xp=0, rng=battle['rng'], rng_draws=0, status='running')
    enter(state)
    if state['player_hp'] == 0:
        state['status'] = 'player-defeated'
    return state


def enter(state):
    enemy = state['definition']['encounters'][state['encounter']]
    state['enemy_hp'] = enemy['hp']
    state['enemy_effects'] = deepcopy(enemy['effects'])
    state['counters'] = [0]*len(enemy['attacks'])


def tick(state, owner, events):
    """Scenario order: DOT/heal at owner's start; all durations expire at end."""
    maximum = state['player_max_hp'] if owner == 'player' else state['definition']['encounters'][state['encounter']]['hp']
    for effect in state[owner+'_effects']:
        before = state[owner+'_hp']
        if effect['kind'] == 'poison':
            state[owner+'_hp'] = max(0, before-quarter_hp_loss(effect['value']))
        elif effect['kind'] == 'regen':
            state[owner+'_hp'] = min(maximum, before+quarter_hp_loss(effect['value']))
        if state[owner+'_hp'] != before:
            events.append(dict(kind=effect['kind'], target=owner, before=before, after=state[owner+'_hp']))
        if state[owner+'_hp'] == 0:
            break


def expire(state, owner):
    effects = state[owner+'_effects']
    for effect in effects:
        effect['turns'] -= 1
    state[owner+'_effects'] = [e for e in effects if e['turns'] > 0]


def skipped(state, owner):
    return any(e['kind'] in ('stun', 'freeze') for e in state[owner+'_effects'])


def multiplier(state, owner, kind):
    return math.prod(e['value'] for e in state[owner+'_effects'] if e['kind'] == kind)


def step(checkpoint, word=None):
    """Copy-on-step; all decisions and shared RNG draws are replayable."""
    validate_checkpoint(checkpoint)
    if checkpoint['status'] != 'running':
        raise ValueError('Campaign ended')
    state = deepcopy(checkpoint)
    definition = state['definition']
    rng = NativeRng()
    rng.restore(NativeRngState(**state['rng']))
    events = []

    def draw(consumer):
        value = rng.next_rand()
        state['rng_draws'] += 1
        events.append(dict(kind='rng', consumer=consumer, index=state['rng_draws'], value=value))
        return value

    def schedule(phase):
        for _ in range(definition['rng_schedule'][phase]):
            draw('scheduled:'+phase)

    class Stream:
        def next_rand(self):
            return draw('refill')

    def refill(path):
        compacted = compact_board(state['board'], path, '*'*len(path))
        state['board'] = compacted['board']
        for slot in compacted['replacement_slots']:
            picked = pick_letter(state['board'], Stream(), definition['initial']['exclusions'], [0]*26)
            letters = list(state['board'].replace('/', ''))
            letters[slot] = picked['letter']
            state['board'] = '/'.join(''.join(letters[i:i+4]) for i in range(0,16,4))
            events.append(dict(kind='refill', slot=slot, letter=picked['letter']))

    def advance():
        enemy = definition['encounters'][state['encounter']]
        reward = enemy['reward']
        state['xp'] += reward['xp']
        state['player_hp'] = min(state['player_max_hp'], state['player_hp']+reward['heal'])
        events.append(dict(kind='encounter-defeated', name=enemy['name'], reward=deepcopy(reward)))
        schedule('encounter')
        state['encounter'] += 1
        if state['encounter'] == len(definition['encounters']):
            state['status'] = 'campaign-complete'
        else:
            enter(state)
            new = definition['encounters'][state['encounter']]
            events.append(dict(kind='encounter-entered', name=new['name'], book=new['book'], chapter=new['chapter']))

    schedule('before-player')
    state['turn'] += 1
    tick(state, 'player', events)
    path = None
    if state['player_hp'] == 0:
        state['status'] = 'player-defeated'
    elif skipped(state, 'player'):
        if word is not None:
            raise ValueError('Skipped player turn requires word=None')
        events.append(dict(kind='turn-skipped', target='player'))
    else:
        if word is None:
            options = [w for w in definition['initial']['words'] if path_for(state['board'], w) is not None]
            if not options:
                state['status'] = 'no-playable-word'
            else:
                word = min(options, key=lambda w: (-damage(w, definition['initial']['offense']).full, len(w), w))
        if state['status'] == 'running':
            path = path_for(state['board'], word)
            if word not in definition['initial']['words'] or path is None:
                raise ValueError('Invalid word')
            amount = quarter_hp_loss(damage(word, definition['initial']['offense']).full
                                     *multiplier(state,'player','power')*multiplier(state,'enemy','shield'))
            state['enemy_hp'] = max(0, state['enemy_hp']-amount)
            events.append(dict(kind='word', word=word, damage=amount, enemy_hp=state['enemy_hp']))
    expire(state, 'player')
    if state['status'] == 'running':
        # Campaign policy refills after lethal words too, preserving a usable rack.
        if path:
            schedule('before-refill')
            refill(path)
        if state['enemy_hp'] == 0:
            advance()
        else:
            schedule('before-enemy')
            tick(state, 'enemy', events)
            if state['enemy_hp'] == 0:
                advance()
            else:
                enemy = definition['encounters'][state['encounter']]
                state['counters'] = [n+1 for n in state['counters']]
                if skipped(state, 'enemy'):
                    events.append(dict(kind='turn-skipped', target='enemy'))
                else:
                    selected = choose_attack(enemy['attacks'], state['counters'], draw)
                    if selected is not None:
                        attack = enemy['attacks'][selected]
                        state['counters'][selected] = 0
                        amount = quarter_hp_loss(attack['damage']*multiplier(state,'enemy','power')
                                                 *multiplier(state,'player','shield'))
                        state['player_hp'] = max(0, state['player_hp']-amount)
                        events.append(dict(kind='enemy-attack', name=attack['name'], damage=amount))
                        if state['player_hp'] > 0:
                            state['player_effects'].extend(deepcopy(attack['effects']))
                expire(state, 'enemy')
                schedule('after-enemy')
                if state['player_hp'] == 0:
                    state['status'] = 'player-defeated'
    snapshot = rng.snapshot()
    state['rng'] = dict(words=list(snapshot.words), cursor=snapshot.cursor)
    return state, events


def simulate(state, max_turns=100):
    integer(max_turns, 'max turns', 1)
    validate_checkpoint(state)
    state = deepcopy(state)
    trace = []
    while state['status'] == 'running' and len(trace) < max_turns:
        state, events = step(state)
        trace.append(dict(turn=state['turn'], events=events))
    return dict(model=MODEL, status=state['status'] if state['status'] != 'running' else 'turn-limit',
                checkpoint=state, trace=trace, native_parity=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--max-turns', type=int, default=100)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.input.read_text())
    state = source['checkpoint'] if args.resume else create(source)
    report = simulate(state, args.max_turns)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(report['status'], len(report['trace']), 'turns')


if __name__ == '__main__':
    main()
