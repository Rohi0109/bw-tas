# Native capture and differential replay

The first capture infrastructure is implemented. A native game-turn comparison
has **not** been recorded yet, and this is not a whole-game checkpoint system.

## Validated capture machinery

`automation/capture_native_rng_gdb.py` uses entry/return breakpoints around the
pinned EXE's engine RNG. Each record contains the caller address, thread, draw
index/value, 624 state words and cursor before and after the draw. It checks the
loaded instructions before placing breakpoints, rejects overlapping/unpaired
calls, writes an explicit completion footer, and detaches after the draw budget.
No RNG state is overwritten or reseeded by the capture script.

The live-process path is:

```sh
python3 automation/capture_native_rng.py --pid GAME_UNIX_PID \
  --game-dir runtime/experiments/sim-capture-v1 \
  --draws 100 --output /tmp/native-rng.jsonl
python3 speedrun/verify_rng_capture.py /tmp/native-rng.jsonl \
  --output /tmp/native-rng-check.json
```

The PID must map the specified EXE, and debugger attachment must be permitted.
This host has `ptrace_scope=1`, which restricts ordinary sibling-process attaches;
do not weaken global ptrace settings just to collect a trial. Use a permitted
debugger-parent launch or an explicitly debug-enabled isolated process. The
capture waits for the requested draw count; it has no wall-clock deadline.
Debugger interruptions alter timing, so these recordings cannot validate timing
or prove an uninstrumented run uses the same cosmetic RNG schedule.

The verifier restores only the first state, then predicts every subsequent draw
and state. It stops at the first mismatch. It does not repair divergence by
loading each recorded predecessor. Missing/reordered draws, interrupted captures,
state discontinuities and unexpected trailing records cannot become a match.
Reseeds intentionally appear as discontinuities; a future seed-event hook is
needed to model them rather than silently resynchronize.

## Executed independent probe

The freestanding `automation/rng_capture_probe.s` fixture executes seed/draw
instruction bytes copied from the pinned EXE as native 32-bit x86 instructions.
It needs GNU assembler/linker and GDB, but no 32-bit libc, Wine or game UI.

```sh
as --32 automation/rng_capture_probe.s -o /tmp/rng-probe.o
ld -m elf_i386 --section-start=.engine=0x5ab440 \
  --section-start=.twist=0x72f914 --section-start=.rng=0x767030 \
  /tmp/rng-probe.o -o /tmp/rng-probe
BWA_CAPTURE_DRAWS=700 BWA_CAPTURE_OUTPUT=/tmp/probe.jsonl \
  BWA_CAPTURE_BUILD='{"fixture":"isolated-executable-RNG-instructions"}' \
  gdb --nx --quiet --batch /tmp/rng-probe \
  -ex 'break capture_ready' -ex run \
  -ex 'source automation/capture_native_rng_gdb.py'
python3 speedrun/verify_rng_capture.py /tmp/probe.jsonl --output /tmp/probe-report.json
```

Executed locally: **700 captured draws and full before/after states matched**,
including a twist boundary. This validates debugger capture plus RNG replay in
an isolated process. It does not validate the Wine attach path, game-turn
scheduling, Lua correlation, enemy AI, or campaign fidelity. Output paths must
be new. The probe requires the exact local EXE; proprietary bytes are not stored
in the repository.

## Isolated pre-submit Lua telemetry

```sh
python3 automation/prepare_sim_capture.py \
  --output runtime/experiments/sim-capture-v1
```

The prepared directory was created locally. The normal installation was not
modified. The patch compiles `DumpSimulationState.lua` and injects one call at
the end of the existing submission logger, before native submission continues.
It records player/enemy scalar state, attack counters and scalar effect fields,
grouped by attack ID. The manifest pins source/capture PAK, EXE and hook hashes.
Compilation and repacking succeeded; native runtime execution is not yet tested.

Effect queues produce an explicit unsupported marker. The hook does not serialize
QRand internals, animation callbacks, full object graphs or a restorable save.
Existing board/selected-slot/damage telemetry remains available. It does not yet
join the debugger's draw index to the Lua attack ID. **Do not treat these two
streams as causally aligned merely because they were collected together.**

## Parent-launch harness — 2026-09-27

`automation/launch_capture.py` replaces manual GDB invocation for the
ptrace_scope=1 case. It uses GDB as process parent (not sibling attach):

```sh
python3 automation/launch_capture.py \
  --game-dir  runtime/experiments/sim-capture-v1 \
  --wine-prefix runtime/experiments/sim-capture-prefix \
  --output-dir runtime/experiments/run-$(date +%Y%m%dT%H%M%S) \
  --draws 700 --timeout 300
```

The harness:
- Checks for duplicate controllers via `/proc` maps before launching.
- Verifies EXE/PAK hashes before starting GDB.
- Starts `gdb --nx --quiet --batch -ex 'source launch_capture_gdb.py' --args wine ...`
- `launch_capture_gdb.py` watches `gdb.events.new_objfile` for the game binary,
  sets a one-shot hardware gate at `0x5ab4b0`, then activates Entry/Returned
  capture (same logic as `capture_native_rng_gdb.py`).
- Enforces `--timeout` wall-clock limit; SIGTERMs the GDB tree on expiry.
- Writes `run-manifest.json` and a combined GDB+game `gdb-combined.log`.
- Lua pre-submit scalars appear in `gdb-combined.log` (Wine stdout mixed with
  GDB output); parse with `automation/capture_log_parser.py`.

Output is verified the same way as probe captures:
```sh
python3 speedrun/verify_rng_capture.py \
  runtime/experiments/run-.../rng-capture.jsonl \
  --output /tmp/verify.json
```

**Remaining gap for P0 gate**: the hardware gate at `0x5ab4b0` fires on the
first engine RNG draw in the live game. The game must progress past the main
menu to produce RNG draws. Navigate to a battle manually or run the TAS
controller against the isolated window (it is isolated from the normal install;
no duplicate controller restriction applies). Once draws begin, the harness
captures them autonomously and detaches at the draw budget.

Confirm the Lua scalar hook (`DumpSimulationState.lua`) executes by checking
`gdb-combined.log` for `AUTOMATION_SIM_BEGIN=` lines after the battle starts.
That satisfies the second part of the P0 gate.

## Next acceptance gate

1. Run `launch_capture.py` against the staged install; navigate to a battle;
   confirm 700 draws with `verify_rng_capture.py` — zero divergence required.
2. Confirm `AUTOMATION_SIM_BEGIN/END` lines appear in `gdb-combined.log`;
   run `capture_log_parser.py` against that log; no quarantined records.
3. Add a shared attack-boundary identifier linking RNG draw indexes to Lua
   attack IDs; add post-turn hidden-state snapshot; validate deduplication.
4. Establish full state restoration or explicitly limit the trial to observable
   primitives. An RNG snapshot alone is not a game checkpoint.
5. Capture repeated identical-state trials before using records as full-turn
   differential fixtures. Use `speedrun/encounter_state.py` eligibility gate.

The initial infrastructure validation used only the isolated native RNG probe.
A subsequent isolated Wine launch reached the game window under a parent GDB
process, but produced no verified live draw/encounter trace before handoff. No
screenshots or live TAS controller were used. The debugger's first-draw gate
handling was then tested on the standalone probe: 700 draws matched in each of
the pre-draw-start and first-draw-gate modes. See the current
[Claude simulator handoff](../CLAUDE_SIM_HANDOFF.md) for launch findings and next steps.
