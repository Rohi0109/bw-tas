# Live validation readiness — 2026-09-28

Ready for a **bounded isolated capture attempt (handoff P0)**. This is not a
claim of full-turn simulator fidelity. The game was not launched during this
readiness pass; Wine startup, native hook execution, and causal Lua/RNG alignment
are the next live checks.

## What was fixed

- Actual hook fields feed a runnable log-to-fixture CLI. Supplementary captured
  state is joined by attack ID; different turns cannot borrow one sidecar.
- Partial RNG/tile arrays are never filled with defaults. Effects, attack keys,
  source log hash, sidecar hash, and parsed evidence are preserved. Player attacks
  are excluded from enemy selection. Errors and quarantines are separate from
  structurally valid fixtures.
- The scalar hook emits collection counts. Missing collection evidence cannot
  prove absence of effects/attacks. Unknown native state, offense interpretation,
  attack order, and effects stay unsupported.
- Launcher validates staged EXE/PAK/hook hashes, checks for existing game/prefix
  processes, locks the isolated prefix, uses absolute artifact paths and the game
  working directory, and cleans up its process group plus its isolated wineserver.
- A hardware gate is armed after loader start even if Wine does not expose a PE
  new_objfile event. Instructions are hash-checked before enabling RNG capture.
- Launcher success requires complete independent RNG replay with the requested
  draw count and matching build identity, successful cleanup, and no timeout.

## Local evidence

Python 3.12.3. Fresh scalar-hook compilation/repacking succeeded in
`runtime/experiments/sim-capture-v2`; normal installation/profile was not changed.
EXE SHA-256:
`7fa527a59ff1108b98b0d18b0625d280029c0fd6c5fb3f91bb2f168b95968c67`.
Staged PAK SHA-256:
`16de2b6b308898b24395e256a0fd6f4533f0f4834d5579030fc31873151b3d41`.

Executed suites: **563 speedrun tests (560 passed, 3 optional skips)** and
**73 automation tests passed**. This includes the CLI joining two distinct
boundaries, malformed/partial evidence, effect preservation, real process-group
cleanup, preflight without launch, exclusive prefix locking, and refusal to
accept corrupted RNG traces or footer-only output. `git diff --check` passed.

Read-only preflight passed for the fresh copy, the existing isolated prefix,
installed tools, and X11 display. Two independent native-instruction capture
controls each matched **700 draws and complete before/after state**, including
one through `launch_capture_gdb.py`'s loader-start hardware gate. Local evidence:
`runtime/experiments/readiness-20260928/{probe,parent-probe}-report.json` and
associated raw traces/logs. These execute RNG instructions outside Wine; they
do not verify game turns. Runtime artifacts remain ignored by Git.

## Next live attempt

From the repository root, first rerun preflight (it launches no game):

```sh
python3 automation/launch_capture.py \
  --game-dir runtime/experiments/sim-capture-v2 \
  --wine-prefix runtime/experiments/sim-capture-prefix \
  --output-dir runtime/experiments/live-validation-next \
  --draws 700 --timeout 300 --preflight-only
```

Run the same command without `--preflight-only` for the bounded capture. Use a
new output directory if it already exists. Only one operator/controller should
navigate the isolated window; do not use the runner's normal `--new-run` path.
No screenshots are needed. Allow for debugger pauses; this is not a timing trial.

Acceptance for the first attempt: 700 real-game draws, complete footer, replay
status `match`, pinned build, and successful cleanup recorded in
`run-manifest.json`. A startup-only trace does not prove the Lua hook ran. Confirm
the scalar hook separately during a bounded word submission, preserving raw
BEGIN/END, creature, attack, collection and effect records. Missing hook output,
gate timeout or crashes are failed/incomplete instrumentation trials, not parity.

## Assemble captured turns

```sh
python3 speedrun/assemble_captures.py path/to/gdb-combined.log \
  --boundaries path/to/boundaries.json --output path/to/new-report.json
```

The sidecar is `{"boundaries": {"ATTACK_ID": boundary, ...}}`. Each boundary
requires `schema_version`, EXE/PAK `build` hashes, `session_id`,
`encounter_instance`, matching integer `attack_id`, `rng_interval`,
`selected_action`, and `observed`. Preserve `teacher_forced` and any
`unsupported_state` reasons. `observed` is an output comparison target only.

Supply separately captured pre-submit inputs under `captured_state`: `board`,
16 `gems`, 16 `tile_powers`, `engine_rng` (624 uint32 `words` and `cursor`), and
`engine_rng_draw_index`; optional `qrand_state` remains unsupported when present.
They must belong to that same boundary/build/session. Hook-owned combat fields
cannot be overwritten by sidecars. Do not populate pre-state from observed
after-state or guess an RNG interval from timestamps. Partial inline data and
conflicting sidecars are rejected, not repaired.

Exit 0 means assembly completed without errors/quarantines; it does **not** mean
native parity. Inspect each structurally valid record's `eligibility` and
`unsupported_fields`. The current native attack-state/ordering/offense mappings
remain unverified, so real hook fixtures must retain unsupported classification.

## Beyond P0

Before full-turn live differential validation, establish a causal draw-index to
attack-boundary bridge, complete captured pre/post state, native AI/state/order
semantics, and independently predicted turns. Reproducible native restore and
alternative-action trials remain open. A copied prefix or 700 matching RNG
draws cannot establish these. Continue the gates in `../CLAUDE_SIM_HANDOFF.md`.
