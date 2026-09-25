# Finish menu-reset optimization

## Assignment

Implement and live-validate faster, reliable menu exit/re-entry. The user wants
measured progress against the WR video, not another mechanics discussion or
instrumentation-only handoff. Preserve solver, RNG, healing and encounter-route
decisions so the timing comparison remains meaningful. Do not claim completion
until actual reset latency improves in controlled game runs.

Preserve the dirty worktree. Keep the game windowed. No screenshots of the
user's live desktop/game without asking; inspection of the downloaded reference
video is already authorized. Use quiet local monitoring and report milestones,
not every frame. Do not launch two input controllers with the same window title.
Use the isolated experiment profile; do not delete the active normal profile.

## What exists and what is unfinished

- `menu_runner.py`: legacy menu/quit/confirmation/Adventure clicks. It retries
  Quit for up to 0.7 seconds awaiting `AUTOMATION_NATIVE_DIALOG=1|E`.
- `menu_trace.py`, `menu_trace_report.py`: optional JSONL cycles and phase
  statistics, with action and observation markers kept separate.
- `continuous_runner.py`: trace integration, map/start-game/READY markers and
  a logged existing 1.25-second re-entry input guard.
- `tas_settings.py`: `--menu-reset-trace PATH` and
  `--menu-reset-mode legacy|observed`. Observed currently rejects startup;
  it is NOT implemented. Legacy remains the working default.
- `MENU_RESET_SPRINT.md`: usage and previous acceptance criteria.

Tests last run: 12 menu tests and 130 continuous-runner tests passed. Rerun
appropriate tests after changes; this is not evidence of live reliability.

## Start with existing evidence

Run from repository root:

```bash
python3 speedrun/menu_trace_report.py runtime/diagnostics/menu-reset.jsonl
```

Read on 2026-09-22: 100 cycles, 100 dialog acknowledgement timeouts, 99 cycles
completed through attack acknowledgement. Across completed cycles, median
times FROM RESET REQUEST are: timeout reached 0.794s, input sequence returned
0.899s, chapter-action acknowledgement 2.810s, READY 5.453s, attack acknowledgement
6.016s. READY-to-attack-request median is 0.074s. These are mixed encounters;
split by encounter and run before comparing candidates.

This trace predates the newest phase markers. Missing map events do not prove
the map never appeared. The 0.794s measurement includes actions before the
0.7s wait; it is not the wait duration itself. Some wait overlaps native screen
transition time. Do not promise 0.7s savings per reset merely by removing it.

WR video: https://www.youtube.com/watch?v=GJlVpQGxxAg (26:45.650).
Downloaded 1080p stream: `/tmp/bwa-video/wr-1080.mp4`; FFmpeg executable:
`/tmp/bwa-video/ffmpeg-7.0.2-amd64-static/ffmpeg`. Temporary files may expire.
Frame/log evidence is in
`runtime/analysis/wr-session-aligned-20260915/video-frame-check-20260921.md`.
At video 00:35.2 and 00:41 the visible log documents two consecutive resets:

| Stage elapsed from reset | War Hound -> Captain | Captain -> Alexander |
|---|---:|---:|
| Menu open | 0.383s | 0.416s |
| Battle torn down | 1.190s | 1.216s |
| Adventure accepted/map visible | 1.754s | 1.807s |
| Engine idle | 2.518s | 2.578s |
| Encounter verified | 3.610s | 3.701s |

Our archived successful run takes 2.845s and 2.826s to its start-game callback,
respectively. Start-game and map-visible are different endpoints. Do not treat
their difference as proven avoidable overhead. The archive is
`runtime/runs/2026-09-14-full-run-023751/`; raw logs are cumulative. Use the exact
successful-run extracts in `runtime/analysis/wr-session-aligned-20260915/`.

## Implementation order

1. **Validate the baseline and trace.** Group by run ID and encounter; retain
   incomplete/failing cycles. Confirm fresh cycles cannot consume queued events
   from a previous reset. Track the actual input-flush timestamp, observation
   receipt timestamp and configured sleep separately. Measure tracing overhead.
   Buffer trace output outside latency-sensitive actions if writing delays input.
   Preserve trace compatibility and explicitly mark unavailable phase data.

2. **Resolve native menu observations.** The current dialog probe runs inside
   BattleEngine Lua, which can stop updating while the native menu is open.
   Locate a read-only observation source that stays available during menu use.
   Inspect existing bindings, native executable and Wine process state. Prefer
   a native update callback already exposed to Lua if it runs through these
   screens; otherwise implement a read-only process-memory observer validated
   against the installed build. Keep the observer behind a narrow snapshot
   interface: timestamp, process/build identity, screen state, battle identity
   and map context when available. Unknown is an explicit state. Identify the
   quit-confirmation dialog specifically; HasDialogs alone is insufficient.
   A frozen tick counter alone also cannot distinguish menu from loading.
   Never invent addresses or infer successful transitions from a sent click.

3. **Implement observed mode.** Put transition control in a dedicated module,
   leaving the main runner readable. Sequence confirmed battle-menu ownership,
   Quit confirmation, teardown/title readiness, Adventure acceptance, then hand
   back to existing map/READY handling. Apply only actions authorized by the
   current observed screen. Use monotonic bounded deadlines and bounded retries;
   retain the existing overall runner timeout. Stop with a diagnostic packet
   on unknown/contradictory persistent state; do not replay a full click sequence
   into an unknown screen. Retain legacy mode for comparison and rollback.
   Preserve existing save-ready gating and all route exceptions.

4. **Measure remaining delays.** Compare matching stages with the WR and legacy.
   Determine whether the 1.25s re-entry guard ever delays input beyond native
   READY. Reduce it only after reproducing and preserving the early War Hound
   tutorial ownership protection. Treat full-log parsing and dialogue pulse
   traffic as separate hypotheses; instrument queue age/processing cost before
   expanding this sprint to a parser rewrite. Earlier CPU benchmarks did not
   prove these were the main source of lost wall-clock time.

## Validation and rollout

Test missing/delayed/stale/duplicate/out-of-order observations, paused Lua,
wrong dialogs, process restarts, ambiguous tick freezes, successful re-entry,
timeouts and immediate cessation of Adventure retries after acknowledgement.
Prove no confirmation click precedes the correct dialog and no rack input
precedes native ownership. Test legacy fallback selection at startup; no blind
mid-transition fallback is allowed.

Start with the isolated fixed-seed environment described in `STATE_GRAPH.md`.
Inspect how its profile is restored and record the checkpoint, seed settings,
build identity and accepted words. `just rng-tas` alone does not restart Chapter 1.
Obtain three baseline and three candidate Chapter 1–4 runs, at least 30 valid
candidate resets, matching progression/accepted-word sequences, lower median
reset-to-READY and no worse p95. Report divergent trials separately, not as wins.
If input timing changes RNG behavior, establish the reproducibility cause before
claiming a controlled comparison. Then complete a full run covering bosses,
Moxie boundaries and the final chapter with zero reset failures or lost progress.

Relevant starting checks:

```bash
PYTHONPATH=speedrun python3 -m unittest discover -s speedrun/tests -p 'test_menu*.py'
PYTHONPATH=speedrun python3 -m unittest discover -s speedrun/tests -p 'test_continuous_runner.py'
git diff --check
```

Only switch the default after live acceptance passes. Deliver code, regression
tests, baseline/candidate artifacts, matched phase timing table, exact commands
and rollback via `--menu-reset-mode legacy`. Update the roadmap with measured
savings and remaining uncertainty. If native observations cannot be established,
document the concrete investigation and missing signal; mark the sprint unfinished
rather than replacing it with another instrumentation milestone.
