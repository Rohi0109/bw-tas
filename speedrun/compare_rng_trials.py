"""Compare observed states/actions carrying a matching submission RNG reset."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from book1_optimizer import action_key
from compare_two_hit_fights import submission_id
from state_graph import identifier, node_payload

RESET = re.compile(r'^AUTOMATION_RNG_RESET=(\d+)\|(\d+)\|submit\|(?:(engine)\|)?E$')


def compare(rows):
    groups, seen, rejected = {}, set(), Counter()
    for row in rows:
        if 'before' not in row or 'after' not in row:
            continue
        attack = submission_id(row)
        resets = [RESET.fullmatch(line) for line in row.get('native_attack_events', [])]
        resets = [r for r in resets if r and int(r[1]) == attack]
        if (attack is None or len(resets) != 1 or not row.get('run_id') or
                not row.get('clean') or row.get('issues') or
                row.get('timing', {}).get('input_attempts') != 1):
            rejected['missing-reset-identity-or-clean-input'] += 1
            continue
        before, after = row['before'], row['after']
        path = row['action']['path']
        letters = before['board'].replace('/', '')
        if (not path or any(type(i) is not int or not 0 <= i < len(letters) for i in path)
                or len(set(path)) != len(path)
                or ''.join(letters[i] for i in path) != row['action']['word']
                or after['sequence'] <= before['sequence']):
            rejected['invalid-action-or-successor'] += 1
            continue
        identity = (row['run_id'], attack, before['sequence'])
        if identity in seen:
            continue
        seen.add(identity)
        # Compare within a chapter. Cross-enemy outcomes are observations,
        # not certified save/reset transitions.
        start = node_payload(before, row['chapter'])
        end = node_payload(after, row['chapter'])
        rng_stream = resets[0][3] or 'crt'
        key = identifier([start, action_key(row['action']['word'], path), int(resets[0][2]), rng_stream])
        group = groups.setdefault(key, dict(enemy=before['enemy'], board=before['board'],
                                           word=row['action']['word'], path=path,
                                           seed=int(resets[0][2]), rng_stream=rng_stream, outcomes={}))
        outcome = group['outcomes'].setdefault(identifier(end), dict(state=end, trials=[]))
        outcome['trials'].append(dict(run_id=row['run_id'], attack_id=attack))
    for group in groups.values():
        sessions = {t['run_id'] for o in group['outcomes'].values() for t in o['trials']}
        group['sessions'] = len(sessions)
        group['status'] = ('diverged' if len(group['outcomes']) > 1 else
                           'three-session-agreement' if len(sessions) >= 3 else
                           'needs-repeats')
    return dict(groups=list(groups.values()), rejected=dict(rejected),
                caveat='Session agreement is observational; full checkpoint restoration and game ticks are not verified.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    with args.source.open() as stream:
        print(json.dumps(compare(json.loads(line) for line in stream if line.strip()), indent=2))
