"""Build an observation graph for Book 1 Chapters 1–4.

Visible state is a projection, not a restorable game checkpoint. Keep every
successor and provenance; repeated log rows never establish determinism.
"""

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

from audit_transition_corpus import classify
from book1_optimizer import action_key, state_from_payload, state_payload
from compare_two_hit_fights import submission_id


def node_payload(payload, chapter):
    state = state_payload(state_from_payload(payload))
    state.pop('sequence')
    # A call counter is not RNG state and is unavailable in current captures.
    state.pop('rng_calls', None)
    if state['chapter'] < 1:
        state['chapter'] = chapter
    return state


def identifier(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(',', ':'), allow_nan=False,
    ).encode()).hexdigest()


def source_lines(source):
    with source.open('rb') as stream:
        yield from stream


def build_graph(source):
    nodes, edges, seen = {}, {}, set()
    rejected = Counter()
    digest = hashlib.sha256()
    for line_number, raw in enumerate(source_lines(source), 1):
        digest.update(raw)
        try:
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError('record must be an object')
        except (ValueError, UnicodeDecodeError):
            rejected['malformed-json'] += 1
            continue
        if row.get('book') != 1 or row.get('chapter') not in range(1, 5):
            continue
        if row.get('record_type') == 'attack-to-zero-health':
            continue
        reasons, _ = classify(row)
        if reasons:
            rejected.update(reasons)
            continue
        attack = submission_id(row)
        if attack is None or not row.get('run_id'):
            rejected['missing-submission-identity'] += 1
            continue
        try:
            before = node_payload(row['before'], row['chapter'])
            after = node_payload(row['after'], row['chapter'])
            start, end = identifier(before), identifier(after)
        except (KeyError, ValueError, TypeError):
            rejected['invalid-state'] += 1
            continue
        # Run ID + native attack + before sequence identify an observation.
        # Distinct outcomes for duplicate identities must not be lost either.
        observation = (row['run_id'], attack, row['before']['sequence'])
        action = action_key(row['action']['word'], row['action']['path'])
        duplicate = (*observation, start, action, end)
        if duplicate in seen:
            rejected['duplicate-observation'] += 1
            continue
        seen.add(duplicate)
        nodes[start], nodes[end] = before, after
        key = identifier([start, action])
        edge = edges.setdefault(key, dict(
            source=start, action=dict(word=row['action']['word'],
                                     path=row['action']['path']), outcomes={},
        ))
        outcome = edge['outcomes'].setdefault(end, dict(target=end, observations=[]))
        outcome['observations'].append(dict(
            run_id=row['run_id'], attack_id=attack,
            before_sequence=row['before']['sequence'], source_line=line_number,
            ready_seconds=row['timing']['ready_seconds'],
            input_seconds=row['timing']['input_seconds'],
        ))
    counts = Counter()
    for edge in edges.values():
        runs = {obs['run_id'] for out in edge['outcomes'].values()
                for obs in out['observations']}
        edge['status'] = ('conflicting-successors' if len(edge['outcomes']) > 1
                          else 'repeated-observation' if len(runs) >= 2
                          else 'single-run-observation')
        edge['independent_runs'] = len(runs)
        edge['deterministic_verified'] = False
        counts[edge['status']] += 1
        for outcome in edge['outcomes'].values():
            times = [o['ready_seconds'] for o in outcome['observations']]
            outcome['wall_time'] = dict(minimum=min(times), maximum=max(times),
                                        median=statistics.median(times))
    return dict(schema_version=1, source=str(source.resolve()),
                source_sha256=digest.hexdigest(), nodes=nodes, edges=edges,
                summary=dict(nodes=len(nodes), edges=len(edges), statuses=dict(counts),
                             rejected=dict(rejected), verified_edges=0),
                limitations=[
                    'Nodes contain observed fields only; hidden battle state and native RNG are missing.',
                    'Elapsed times are wall seconds, not native game ticks.',
                    'Repeated outcomes do not prove deterministic restoration.',
                    'Encounter changes and menu resets need separate transition validation.',
                    'No unplayed successor or automatic live override is generated.',
                ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path,
                        default=Path('runtime/deluxe-modded/tas-timing.jsonl'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    graph = build_graph(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(graph, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(graph['summary'], indent=2))


if __name__ == '__main__':
    main()
