"""Extract structurally usable observations; never infer unplayed successors."""

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def refill_layout(before, after, path):
    """Check column gravity; return survivor mapping and observed refill slots.

    New letters are observations only. No RNG or generation order is inferred.
    """
    used = set(path)
    mapping, replacements = [], []
    for column in range(4):
        slots = list(range(column, 16, 4))
        survivors = [i for i in slots if i not in used]
        count = len(slots) - len(survivors)
        for source, destination in zip(survivors, slots[count:]):
            if before[source] != after[destination]:
                return None
            mapping.append([source, destination])
        replacements.extend(slots[:count])
    return dict(survivor_mapping=mapping, replacement_slots=replacements,
                observed_replacement_letters=[after[i] for i in replacements])


def classify(row):
    reasons = []
    notes = []
    try:
        before, action, after = (row[k] for k in ('before', 'action', 'after'))
        letters = before['board'].replace('/', '')
        next_letters = after['board'].replace('/', '')
        path = action['path']
        if len(letters) != 16 or len(next_letters) != 16:
            reasons.append('invalid-board-size')
        if not path or any(type(i) is not int or not 0 <= i < 16 for i in path):
            reasons.append('invalid-path')
        elif len(letters) == 16:
            if len(set(path)) != len(path):
                reasons.append('reused-tile')
            if ''.join(letters[i] for i in path) != action['word']:
                reasons.append('path-word-mismatch')
            if len(next_letters) == 16:
                if refill_layout(letters, next_letters, path) is None:
                    reasons.append('column-survivors-mismatch')
                else:
                    notes.append('column-compaction-consistent')
        if after['sequence'] <= before['sequence']:
            reasons.append('nonadvancing-sequence')
        if all(before[k] == after[k] for k in ('board', 'hp', 'enemy')):
            reasons.append('unchanged-board-hp-enemy')
        if not row.get('clean') or row.get('issues'):
            reasons.append('input-or-record-issues')
        timing = row['timing']
        if timing.get('input_attempts') != 1:
            reasons.append('input-attempts-not-one')
        ready, input_time = timing['ready_seconds'], timing['input_seconds']
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (ready, input_time)):
            reasons.append('invalid-timing')
        elif not 0 <= input_time < ready:
            reasons.append('invalid-timing-order')
        for name, state in (('before', before), ('after', after)):
            for field in ('gems', 'tile_powers', 'selectable', 'zero_damage'):
                if len(state.get(field, [])) != 16:
                    reasons.append(f'{name}-missing-{field}')
            if state.get('book') != 1:
                reasons.append(f'{name}-book-mismatch')
        if before.get('chapter', -1) < 1:
            notes.append('before-chapter-from-outer-context')
        elif before['chapter'] != row['chapter']:
            reasons.append('conflicting-chapter')
        same_encounter = all(before[k] == after[k] for k in ('book', 'stage', 'enemy'))
        if not same_encounter:
            reasons.append('encounter-transition-needs-route-validation')
        elif after['hp'] >= before['hp']:
            reasons.append('no-net-enemy-damage')
        rng_known = all(s.get('rng_calls', -1) >= 0 for s in (before, after))
        if not rng_known:
            notes.append('rng-unavailable')
        elif after['rng_calls'] < before['rng_calls']:
            reasons.append('rng-moved-backwards')
    except (KeyError, TypeError, ValueError):
        reasons.append('incomplete-or-malformed-record')
    return sorted(set(reasons)), notes


def audit(source, output):
    output.mkdir(parents=True, exist_ok=True)
    coverage = defaultdict(Counter)
    totals = Counter()
    reasons_total = Counter()
    digest = hashlib.sha256()
    with source.open('rb') as stream, (output / 'observations.jsonl').open('w') as accepted, (output / 'quarantine.jsonl').open('w') as quarantine:
        for number, raw in enumerate(stream, 1):
            digest.update(raw)
            totals['source_lines'] += 1
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                totals['malformed_lines'] += 1
                continue
            if not isinstance(row, dict) or row.get('book') != 1 or row.get('chapter') not in range(1, 10):
                continue
            chapter = row['chapter']
            coverage[chapter]['rows'] += 1
            if row.get('record_type') == 'attack-to-zero-health':
                coverage[chapter]['kill_timing_rows'] += 1
                continue
            reasons, notes = classify(row)
            coverage[chapter]['transition_rows'] += 1
            coverage[chapter]['quarantined' if reasons else 'structurally_usable'] += 1
            if chapter > 4:
                continue
            compact = {k: v for k, v in row.items() if k not in ('frontier',)}
            compact['audit'] = dict(source_line=number, reasons=reasons, notes=notes)
            if not reasons:
                compact['audit']['refill'] = refill_layout(
                    row['before']['board'].replace('/', ''),
                    row['after']['board'].replace('/', ''), row['action']['path'])
            # Raw before/after states remain intact; -1 chapters are not silently
            # rewritten. These are observations, not a live lookahead oracle.
            target = quarantine if reasons else accepted
            target.write(json.dumps(compact, sort_keys=True) + '\n')
            totals['quarantined_ch1_4' if reasons else 'usable_ch1_4'] += 1
            reasons_total.update(reasons)
    report = dict(source=str(source.resolve()), source_sha256=digest.hexdigest(),
                  totals=dict(totals), coverage=dict(coverage), quarantine_reasons=dict(reasons_total),
                  limitations=['Structural checks do not establish attack acknowledgement or exact causality.',
                               'Timing is wall clock, not native animation frame counts.',
                               'Encounter changes are quarantined pending route/reset validation.',
                               'Repeated observations are retained; they are not independent experiments.',
                               'No replacement RNG model or counterfactual successor is inferred.'])
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('runtime/deluxe-modded/tas-timing.jsonl'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output directory to preserve prior audits.')
    print(json.dumps(audit(args.source, args.output), indent=2))
