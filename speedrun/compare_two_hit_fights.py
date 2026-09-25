"""Offline Ch1–4 attack-time comparison; never invent counterfactual refills."""

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

from audit_transition_corpus import classify
from book1_optimizer import candidate_payload, state_from_payload, state_fingerprint
from deluxe_optimizer import candidates, choose, index_words


def plain_rack(state):
    return (not any(state.tile_powers) and not any(state.zero_damage)
            and all(g == 'none' for g in state.gems)
            and all(state.selectable) and state.player_damage_multiplier == 1
            and not any((state.player_stunned, state.player_frozen,
                         state.player_petrified, state.player_has_damage_over_time))
            and state.treasures <= {'bow of zyx', 'golden fleece', "poseidon's shield", 'icarus sandals'})


def survivor_plans(state, words, click_delay=.01):
    """Conditional pairs: surviving letters only, no enemy turn/status model.

    Plain duplicate tiles are interchangeable. Search word pairs by letter
    counts, then allocate the second path strictly outside the first path.
    """
    if not plain_rack(state):
        raise ValueError('Survivor search requires a supported plain rack')
    ranked = candidates(state, words, frozenset(), click_delay)
    fastest = sorted(ranked, key=lambda c: (c.predicted_time, len(c.word), c.word))
    counts = {c.word: Counter(c.word) for c in ranked}
    available = Counter(state.board.replace('/', ''))
    plans = []
    for first in ranked:
        if first.lethal:
            plans.append(dict(first=candidate_payload(first), second=None,
                              attack_time_proxy=first.predicted_time))
            continue
        remaining_hp = state.hp-first.damage
        remaining_letters = available-counts[first.word]
        for second in fastest:
            if second.damage + 1e-9 < remaining_hp:
                continue
            if any(n > remaining_letters[c] for c, n in counts[second.word].items()):
                continue
            survivors = replace(state, hp=remaining_hp,
                                selectable=tuple(i not in first.path for i in range(16)))
            allocated = candidates(survivors, [second.word], frozenset(), click_delay)[0]
            plans.append(dict(first=candidate_payload(first), second=candidate_payload(allocated),
                              attack_time_proxy=first.predicted_time+allocated.predicted_time))
            break
    return sorted(plans, key=lambda p: (p['attack_time_proxy'], p['first']['word']))


def submission_id(row):
    matches = [re.search(r'AUTOMATION_ATTACK_ID=(\d+)\|([^|]+)\|([^|]+)\|E', line)
               for line in row.get('native_attack_events', [])]
    matches = [m for m in matches if m]
    if len(matches) != 1:
        return None
    match = matches[0]
    if match[2] != row['before']['enemy'] or match[3].replace('QU', 'Q') != row['action']['word']:
        return None
    return int(match[1])


def compare_row(row, words, click_delay):
    before, after = state_from_payload(row['before']), state_from_payload(row['after'])
    ranked = candidates(before, words, frozenset(), click_delay)
    recorded = next((c for c in ranked if c.word == row['action']['word']
                     and list(c.path) == row['action']['path']), None)
    if recorded is None:
        raise ValueError('Recorded action is absent from the current candidate set')
    finishers = [c for c in candidates(after, words, frozenset(), click_delay) if c.lethal]
    best_finish = min(finishers, key=lambda c: (c.predicted_time, c.word)) if finishers else None
    plans = survivor_plans(before, words, click_delay)
    baseline = recorded.predicted_time+best_finish.predicted_time if best_finish else None
    best = plans[0] if plans else None
    # This frontier is a shortlist for experiments, NOT valid multi-turn
    # dominance pruning: even equal damage/time words leave different letters.
    tradeoffs = []
    for candidate in sorted(ranked, key=lambda c: (c.predicted_time, -c.damage, c.word)):
        if tradeoffs and candidate.damage <= tradeoffs[-1].damage:
            continue
        tradeoffs.append(candidate)
    return dict(run_id=row['run_id'], source_line=row['_source_line'],
                state_fingerprint=state_fingerprint(before),
                attack_id=submission_id(row), chapter=row['chapter'], enemy=before.enemy,
                board=before.board, hp=before.hp, recorded_first=candidate_payload(recorded),
                recorded_next_board=after.board, recorded_next_hp=after.hp,
                best_finish_on_recorded_board=candidate_payload(best_finish) if best_finish else None,
                recorded_branch_attack_proxy=baseline,
                observed_first_to_ready_seconds=row['timing']['ready_seconds'],
                current_dps_choice=candidate_payload(choose(ranked, 'shortest-lethal')[0]),
                first_hit_tradeoffs=[dict(action=candidate_payload(c), remaining_hp=max(0, before.hp-c.damage),
                                          successor='unknown-refill') for c in tradeoffs],
                conditional_survivor_plans=plans[:10], survivor_plan_count=len(plans),
                conditional_proxy_saving=baseline-best['attack_time_proxy'] if baseline is not None and best else None,
                assumptions=['No enemy healing, status effects, tile theft, or letter mutation between hits.',
                             'Second paths use ORIGINAL pre-gravity slot indices; not executable click overrides.',
                             'Attack proxy excludes enemy response, menus, and unmodeled presentation delays.',
                             'Counterfactual first actions have not been played; this is not proven saved time.'])


def report(source, output, run_id, words, click_delay=.01):
    results, rejected, seen = [], Counter(), set()
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        for number, raw in enumerate(stream, 1):
            digest.update(raw)
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if row.get('run_id') != run_id or row.get('book') != 1 or row.get('chapter') not in range(1, 5):
                continue
            if 'before' not in row or 'after' not in row:
                continue
            # This comparison concerns first hits which leave the same enemy alive.
            if row['before']['enemy'] != row['after']['enemy'] or row['after']['hp'] <= 0:
                continue
            reasons, _ = classify(row)
            if reasons:
                rejected.update(reasons)
                continue
            identifier = submission_id(row)
            if identifier is None:
                rejected['ambiguous-submission'] += 1
                continue
            if identifier in seen:
                continue
            seen.add(identifier)
            if not all(plain_rack(state_from_payload(row[k])) for k in ('before', 'after')):
                rejected['outside-plain-rack-scope'] += 1
                continue
            row['_source_line'] = number
            results.append(compare_row(row, words, click_delay))
    result = dict(run_id=run_id, source=str(source.resolve()), source_sha256=digest.hexdigest(),
                  click_delay=click_delay, compared=len(results), rejected=dict(rejected), fights=results,
                  limitations=['No live solver changes or automatic branch overrides.',
                               'Recorded refill is used ONLY for the recorded first action.',
                               'Word-pair search covers supported plain racks, not an optimal full-game route.'])
    output.mkdir(parents=True, exist_ok=False)
    (output/'report.json').write_text(json.dumps(result, indent=2)+'\n')
    # One state/action override per file: independent trials, never auto-loaded.
    for fight in results:
        for trial in fight['first_hit_tradeoffs']:
            action = trial['action']
            if action['word'] == fight['recorded_first']['word']:
                continue
            if action['damage'] <= fight['recorded_first']['damage']:
                continue
            filename = f"trial-{fight['attack_id']}-{action['word']}.json"
            experiment = dict(decisions={fight['state_fingerprint']: dict(word=action['word'], path=action['path'])},
                              baseline_run=run_id, enemy=fight['enemy'],
                              warning='Unplayed experiment, not an optimized route. Applies only to the exact recorded state.')
            (output/filename).write_text(json.dumps(experiment, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('runtime/deluxe-modded/tas-timing.jsonl'))
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--click-delay', type=float, default=.01)
    args = parser.parse_args()
    words = index_words(list(json.loads(Path('speedrun/word_dict.json').read_text())))
    result = report(args.source, args.output, args.run_id, words, args.click_delay)
    print(json.dumps({k: result[k] for k in ('run_id', 'compared', 'rejected')}, indent=2))
