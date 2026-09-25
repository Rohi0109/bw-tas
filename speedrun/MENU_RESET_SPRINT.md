# Menu reset sprint: instrumentation ready, optimization gated

Legacy reset behavior remains the default. `--menu-reset-mode observed` fails
at argument validation, before profile changes or input: no native-menu state
reader has been validated. Do not remove the 0.7-second guard blindly.

## Baseline capture

Start the isolated fixed-seed game in windowed mode with `just rng-game` only
when the regular game is closed (both use the same title). At the intended
experiment starting state, run:

```
just rng-tas --menu-reset-mode legacy --menu-reset-trace runtime/experiments/engine-seed-game/menu-reset-baseline.jsonl
python3 speedrun/menu_trace_report.py runtime/experiments/engine-seed-game/menu-reset-baseline.jsonl
```

The trace appends unique cycle IDs and the experiment run ID. Archive each
trial with its matching logs, seed/build identity and word sequence. Launching
the runner does not reset the experiment to Chapter 1; use the established
experiment-profile setup to produce comparable trials. No profile is reset by
the new options. For a currently running regular game, an opt-in diagnostic
attachment is `just monitor --menu-reset-trace runtime/diagnostics/menu-reset.jsonl`.
This preserves its current profile but continues automated gameplay.

Without `--menu-reset-trace`, no new handler or trace writes run. Rollback to
the existing input behavior is `--menu-reset-mode legacy` (already default).

## What is measured

The phase report now separates map detection from the `start-game` callback.
Compare WR map-up only with `reset_to_map`; if no map event is received the
report lists it as missing instead of substituting start-game. The current
BookManager hook may not emit during every mid-chapter re-entry.
`phase_seconds` also measures time inside menu/quit/confirmation action calls,
the actual dialog acknowledgement wait, start-game-to-READY and
READY-to-attack request. Action-call durations include configured waits and
do not confirm screen ownership. All observations are timestamped on receipt
by Python, not at the native frame; buffered events can arrive later.

The runner additionally records when the existing 1.25-second re-entry READY
guard is armed. Its duration can overlap loading; do not count 1.25 seconds
as savings without checking READY and input timestamps. Completion now covers
the presentation-skip acknowledgement path as well as the normal submission.
Native menu-open and battle-teardown confirmations remain unavailable; these
cannot be inferred from an input-action return.

Each cycle records the last reported state and reset reason where available,
monotonic action timestamps, acknowledgement versus timeout, Quit retry count,
Adventure retries, chapter actions, accepted READY sequence and next attack
acknowledgement. Actions are not screen observations. Interrupted/superseded
cycles remain incomplete. JSONL is authoritative; INFO has a completion summary.
The report excludes incomplete cycles from timing percentiles. Run telemetry
must still be inspected to establish encounter progress and word equivalence.

## Gate and next work

The archived successful Lua log contains zero positive native-dialog events.
The detector calls `gCApp:HasDialogs()` inside BattleEngine's Lua update hook;
the code itself warns this hook can suspend during native menus. Existing X11
helpers inject input and inspect window geometry, not internal menu ownership.
The RNG bridge is an executable patch, not a read-only native-state reader.

Missing observations: positive battle-menu ownership, identity of the quit
confirmation, battle teardown, and main-menu readiness while Lua is paused.
A frozen tick counter alone is ambiguous. Locate and validate these signals
before implementing the observed path. No screenshot or executable modification
has been introduced. Until then there is no candidate speedup to live-validate.

Acceptance remains three baseline/candidate fixed-seed Chapter 1–4 pairs,
at least 30 clean reset cycles, identical accepted words/progression, improved
median reset-to-READY and no worse p95, followed by one full clean run.
