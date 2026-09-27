"""Differentially replay native engine RNG capture, stopping at first divergence."""
import argparse
import json
from pathlib import Path

from native_rng import NativeRng, NativeRngState


def verify(records):
    records = iter(records)
    header = next(records, {})
    if header.get('kind') != 'header' or header.get('schema_version') != 1:
        raise ValueError('Missing native capture header')
    rng = NativeRng()
    count = 0
    for row in records:
        if row.get('kind') == 'end':
            complete = (row.get('complete') is True and row.get('draws') == count
                        and count > 0 and not row.get('pending') and not row.get('error'))
            if next(records, None) is not None:
                raise ValueError('Data after capture footer')
            return dict(status='match' if complete else 'incomplete', draws_checked=count,
                        build=header.get('build'), full_game_parity=False)
        if row.get('kind') != 'draw' or row.get('index') != count+1:
            raise ValueError('Missing, duplicate or out-of-order draw')
        before = NativeRngState(tuple(row['before']['words']), row['before']['cursor'])
        if count == 0:
            rng.restore(before)
        elif rng.snapshot() != before:
            return dict(status='diverged', draw=count+1, field='before-state',
                        reason='Uncaptured draw, reseed, state write or reordered trace')
        predicted = rng.next_rand()
        after = NativeRngState(tuple(row['after']['words']), row['after']['cursor'])
        if predicted != row['value'] or rng.snapshot() != after:
            return dict(status='diverged', draw=count+1,
                        field='value' if predicted != row['value'] else 'after-state',
                        predicted_value=predicted, observed_value=row['value'])
        count += 1
    return dict(status='incomplete', draws_checked=count, reason='Missing capture footer')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.capture.open() as source:
        report = verify(json.loads(line) for line in source if line.strip())
    with args.output.open('x') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'match' else 1


if __name__ == '__main__':
    raise SystemExit(main())
