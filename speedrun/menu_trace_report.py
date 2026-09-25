"""Summarize observed reset phases; incomplete cycles are reported separately."""
import argparse
import collections
import json
import math
import statistics


def summarize(rows):
    cycles = collections.defaultdict(list)
    for row in rows:
        cycles[row['cycle_id']].append(row)
    completed = [r for r in cycles.values() if any(x.get('status') == 'complete' for x in r)]
    phases = {}
    def stats(values):
        values = sorted(values)
        return dict(count=len(values), median=statistics.median(values),
                    p95=values[math.ceil(.95*len(values))-1])
    for stage in ('dialog_acknowledged', 'dialog_ack_timeout', 'reset_input_sequence_returned',
                  'chapter_action_observed', 'battle_ready_observed', 'attack_acknowledged'):
        values = sorted(next(x['elapsed'] for x in r if x['stage'] == stage)
                        for r in completed if any(x['stage'] == stage for x in r))
        if values:
            phases[stage] = dict(count=len(values), median=statistics.median(values),
                                 p95=values[math.ceil(.95*len(values))-1])
    intervals = {}
    # Include partial cycles when both endpoints exist, and never substitute
    # a sent click for an observed screen. Times are host receipt timestamps.
    pairs = {
        'menu_action_call': ('battle_menu_action_sent', 'battle_menu_action_returned'),
        'quit_action_call': ('quit_action_sent', 'quit_action_returned'),
        'dialog_wait_timeout': ('dialog_ack_wait_started', 'dialog_ack_timeout'),
        'dialog_wait_confirmed': ('dialog_ack_wait_started', 'dialog_acknowledged'),
        'confirm_action_call': ('confirm_quit_action_sent', 'confirm_quit_action_returned'),
        'reset_to_map': ('reset_requested', 'chapter_map_observed'),
        'adventure_sent_to_map': ('adventure_action_sent', 'chapter_map_observed'),
        'reset_to_start_game': ('reset_requested', 'start_game'),
        'start_game_to_ready': ('start_game', 'battle_ready_observed'),
        'ready_to_attack_request': ('battle_ready_observed', 'attack_requested'),
    }
    for label, (start, end) in pairs.items():
        values = []
        for rows in cycles.values():
            first = {}
            for row in rows:
                stage = row['stage']
                if stage == 'chapter_callback_observed' and row.get('action') == 'start-game':
                    stage = 'start_game'
                first.setdefault(stage, row['elapsed'])
            if start in first and end in first and first[end] >= first[start]:
                values.append(first[end]-first[start])
        if values:
            intervals[label] = stats(values)
    missing = {stage: sum(not any(r['stage'] == stage for r in rows) for rows in cycles.values())
               for stage in ('dialog_acknowledged', 'chapter_map_observed', 'battle_ready_observed')}
    return dict(cycles=len(cycles), completed=len(completed), incomplete=len(cycles)-len(completed),
                seconds_since_reset_request=phases,
                phase_seconds=intervals, cycles_without_observation=missing,
                caveat='Host observation times; action calls include configured waits and do not prove screen ownership.',
                dialog_timeouts=sum(x['stage'] == 'dialog_ack_timeout' for r in cycles.values() for x in r))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace')
    args = parser.parse_args()
    with open(args.trace) as stream:
        print(json.dumps(summarize(json.loads(line) for line in stream if line.strip()), indent=2))
