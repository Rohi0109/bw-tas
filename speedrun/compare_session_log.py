"""Read-only comparison of an external session log with an archived TAS run.

The two log formats expose different clocks and attack markers. Output keeps
those distinctions; differences are observations, not causal speedup estimates.
"""

import argparse
import bisect
import collections
import json
from pathlib import Path
import re
import statistics
import csv
from datetime import datetime
from zoneinfo import ZoneInfo


def duration(value):
    return f'{int(value // 60)}:{value % 60:06.3f}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, help='new directory for report and exact-run log extracts')
    parser.add_argument('--log-timezone', default='America/New_York')
    args = parser.parse_args()
    timer = json.loads((args.archive / 'run-timer.json').read_text())
    ours_raw = (args.archive / 'tas-live.log').read_text().splitlines()
    # The earlier "current" exports accidentally started at the first new-run
    # marker. Select the LAST fresh-run marker preceding the final completion.
    end = max(i for i, line in enumerate(ours_raw) if 'campaign complete.' in line)
    start = max(i for i, line in enumerate(ours_raw[:end])
                if 'Solver preloaded; recreating the TAS profile.' in line)
    ours_raw = ours_raw[start:end+1]
    assert len(timer['splits']) == 30 and timer['finished_at'] is not None
    ours = []
    for number, line in enumerate(ours_raw, start+1):
        match = re.match(r'(\d\d:\d\d:\d\d\.\d+) (\w+) (.*)', line)
        if match:
            clock = datetime.strptime(match[1], '%H:%M:%S.%f')
            seconds = clock.hour * 3600 + clock.minute * 60 + clock.second + clock.microsecond/1e6
            ours.append(dict(t=seconds, level=match[2], text=match[3], line=number))
    reference = []
    for number, line in enumerate(args.reference.read_text().splitlines(), 1):
        match = re.search(r'\[.*?\+\s*([\d.]+)\] (.*)', line)
        if match:
            reference.append(dict(t=float(match[1]), text=match[2], line=number))
    ref_end = next(e['t'] for e in reference if 'run complete:' in e['text'])
    ref_start = next(e['t'] for e in reference if 'clicking OK (accept default name)' in e['text'])
    ref_boundaries = [e['t'] for e in reference if e['text'] == 'kill: chapter end reached']
    assert len(ref_boundaries) == 29
    ref_boundaries.append(ref_end)
    ours_start = datetime.fromtimestamp(timer['started_at'], ZoneInfo(args.log_timezone))
    ours_start = ours_start.hour*3600 + ours_start.minute*60 + ours_start.second + ours_start.microsecond/1e6
    ours_boundaries = [ours_start + s['ended_at'] - timer['started_at'] for s in timer['splits']]
    groups = {k: collections.defaultdict(list) for k in ['ours','ref']}
    for name, events, bounds in [('ours',ours,ours_boundaries), ('ref',reference,ref_boundaries)]:
        for event in events:
            chapter = min(bisect.bisect_right(bounds, event['t']), 29)
            groups[name][chapter].append(event)
    def words(events, name):
        pattern = (r'Attack (\d+): ([A-Z/]+) -> ([A-Z]+)' if name == 'ours'
                   else r"Logged comprehensive trace for '([^']+)'")
        return [dict(**e, word=m[3] if name=='ours' else m[1])
                for e in events if (m:=re.search(pattern, e['text']))]
    def resets(events, name):
        return [e for e in events if
                (('menu reset after ' in e['text'] or 'immediate reset through the main menu' in e['text'])
                 if name=='ours' else 'reset: menu opened' in e['text'])]
    rows=[]
    for index, split in enumerate(timer['splits']):
        previous = ref_boundaries[index-1] if index else ref_start
        ref_seconds = ref_boundaries[index] - previous
        row = dict(chapter=f"{split['book']}.{split['chapter']}", ours_seconds=split['elapsed'],
                   reference_seconds=ref_seconds, gap=split['elapsed']-ref_seconds)
        for name in ['ours','ref']:
            events=groups[name][index]
            word_events=words(events,name)
            row[name+'_words']=[e['word'] for e in word_events]
            row[name+'_resets']=len(resets(events,name))
            boundary = (ours_boundaries[index-1] if index else ours_start) if name=='ours' else previous
            row[name+'_boundary_to_first_word_marker'] = word_events[0]['t']-boundary if word_events else None
        rows.append(row)
    # Match functional chapter boundaries instead of comparing our next-chapter
    # entry timer with the reference's boss-death timer. Our word marker is before
    # input; theirs is after submission, so these remain approximate comparisons.
    for index, row in enumerate(rows):
        for name in ('ours', 'ref'):
            first = words(groups[name][index], name)[0]['t']
            following = (words(groups[name][index+1], name)[0]['t'] if index < 29
                         else (ours_start + timer['finished_at']-timer['started_at']
                               if name == 'ours' else ref_end))
            row[name+'_first_word_to_next_chapter_seconds'] = following-first
    summary=dict(ours_seconds=timer['finished_at']-timer['started_at'],
                 reference_session_seconds=ref_end,
                 reference_name_click_to_finish=ref_end-ref_start,
                 gap_seconds=timer['finished_at']-timer['started_at']-(ref_end-ref_start),
                 ours_source_start_line=start+1, ours_source_end_line=end+1,
                 ours_attack_attempts=len(words(ours,'ours')),
                 reference_word_traces=len(words(reference,'ref')),
                 ours_reset_messages=len(resets(ours,'ours')),
                 reference_menu_open_messages=len(resets(reference,'ref')))
    # Ordinary reset intervals only, using each logger's documented endpoints.
    ref_reset_intervals=[]
    ref_resume_word_intervals=[]
    start_event=None
    position=None
    for event in reference:
        if event['text']=='kill: next enemy engaged, board settled; resetting': start_event=event
        if 'position after reset:' in event['text']:
            position=event
            if start_event:
                ref_reset_intervals.append(event['t']-start_event['t'])
                start_event=None
        if 'Logged comprehensive trace for' in event['text'] and position:
            ref_resume_word_intervals.append(event['t']-position['t']); position=None
    ours_reset_intervals=[]
    pending=None
    for event in ours:
        if 'menu reset after ' in event['text']: pending=event
        if re.match(r'Attack \d+:', event['text']) and pending:
            ours_reset_intervals.append(event['t']-pending['t']); pending=None
    def stats(values):
        return dict(n=len(values), total=sum(values), median=statistics.median(values)) if values else {}
    summary['reference_ordinary_kill_to_position']=stats(ref_reset_intervals)
    summary['reference_position_to_word_trace']=stats(ref_resume_word_intervals)
    summary['ours_ordinary_reset_to_attack_start']=stats(ours_reset_intervals)
    summary['ours_adventure_retry_messages']=sum('Retrying Adventure' in e['text'] for e in ours)
    summary['ours_health_potion_confirmations']=sum('health-potion consumption confirmed' in e['text'] for e in ours)
    summary['books'] = [dict(book=b, ours_seconds=sum(r['ours_seconds'] for r in rows[(b-1)*10:b*10]),
                            reference_seconds=sum(r['reference_seconds'] for r in rows[(b-1)*10:b*10]))
                        for b in (1,2,3)]
    summary['word_lengths']={name:stats([len(e['word']) for e in words(events,name)])
                             for name,events in [('ours',ours),('ref',reference)]}
    summary['timing_caveat'] = ('Raw chapter splits have different boundaries: ours ends at next chapter entry, '
        'reference at chapter-end kill. Aligned chapter intervals use first word to next chapter first word; '
        'ours logs before input, reference after submission. Neither supports exact causal speedup estimates.')
    result=dict(summary=summary, chapters=rows)
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output/'comparison.json').write_text(json.dumps(result, indent=2)+'\n')
        with (args.output/'chapters.csv').open('w') as stream:
            writer=csv.writer(stream)
            writer.writerow(['chapter','ours_seconds','reference_seconds','gap_seconds','ours_attempts','reference_word_traces',
                             'ours_reset_messages','reference_menu_open_messages',
                             'ours_first_word_to_next_chapter_seconds','reference_first_word_to_next_chapter_seconds'])
            for row in rows:
                writer.writerow([row['chapter'],row['ours_seconds'],row['reference_seconds'],row['gap'],
                                 len(row['ours_words']),len(row['ref_words']),row['ours_resets'],row['ref_resets'],
                                 row['ours_first_word_to_next_chapter_seconds'],row['ref_first_word_to_next_chapter_seconds']])
        for level in ('INFO','DEBUG','WARNING','ERROR'):
            (args.output/f'ours-{level.lower()}.log').write_text(''.join(
                ours_raw[e['line']-start-1]+'\n' for e in ours if e['level']==level))
        print(json.dumps(summary, indent=2))
        print('Report:', args.output)
    else:
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
