"""Replay explicit picker calls and intervening engine draws offline.

This is a differential-test building block, not an inferred gameplay schedule.
Each pick supplies the board as seen by that call, including tile presence.
"""

import argparse
import json
from pathlib import Path

from native_letter_picker import load_exclusions, pick_letter
from native_rng import NativeRng, NativeRngState


def replay(initial_state, events, excluded):
    """Run an explicit schedule on private RNG state; never mutate the caller.

    Expected letters/draws are optional independent observations. Mismatches
    are reported without forcing RNG or board state to match the observation.
    """
    rng = NativeRng()
    rng.restore(initial_state)
    records = []
    for index, event in enumerate(events):
        kind = event.get('kind')
        if kind == 'draws':
            if set(event) != {'kind', 'count'}:
                raise ValueError('draws requires only kind and count')
            count = event['count']
            if type(count) is not int or not 0 <= count <= 100000:
                raise ValueError('draw count must be in 0..100000')
            draws = [rng.next_rand() for _ in range(count)]
            records.append(dict(index=index, kind=kind, draws=draws))
        elif kind == 'pick':
            required = {'kind', 'board', 'extras', 'restrict_duplicates'}
            if not required <= set(event) or set(event) - required - {'expected_letter', 'expected_draw'}:
                raise ValueError('pick requires board, extras and explicit caller flag')
            if 'expected_letter' in event and (not isinstance(event['expected_letter'], str)
                    or len(event['expected_letter']) != 1 or not 'A' <= event['expected_letter'] <= 'Z'):
                raise ValueError('expected_letter must be A-Z')
            if 'expected_draw' in event and (type(event['expected_draw']) is not int
                    or not 0 <= event['expected_draw'] <= 0x7fffffff):
                raise ValueError('expected_draw must be a native 31-bit draw')
            result = pick_letter(event['board'], rng, excluded, event['extras'],
                                 restrict_duplicates=event['restrict_duplicates'])
            mismatches = [field for field in ('letter', 'draw')
                          if 'expected_' + field in event
                          and event['expected_' + field] != result[field]]
            records.append(dict(index=index, kind=kind, board=event['board'],
                                **result, mismatches=mismatches))
        else:
            raise ValueError(f'Unknown event kind: {kind!r}')
    state = rng.snapshot()
    return dict(schema_version=1, model='explicit-picker-schedule-v1',
                events=records, final_rng=dict(words=state.words, cursor=state.cursor),
                mismatch_count=sum(len(r.get('mismatches', [])) for r in records),
                limitations=['Boards, caller flags, extra frequencies and draw scheduling are supplied inputs.',
                             'No enemy turns, Lua callbacks, tile insertion or native timing are simulated.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('schedule', type=Path)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    schedule = json.loads(args.schedule.read_text())
    if schedule.get('model') != 'explicit-picker-schedule-v1':
        raise ValueError('Explicit model explicit-picker-schedule-v1 required')
    state = schedule['initial_rng']
    report = replay(NativeRngState(tuple(state['words']), state['cursor']),
                    schedule['events'], load_exclusions(args.executable))
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(f"{len(report['events'])} events; {report['mismatch_count']} mismatches")


if __name__ == '__main__':
    main()
