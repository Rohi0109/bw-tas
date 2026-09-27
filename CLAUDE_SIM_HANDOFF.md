# Claude Code handoff: native-validated internal Bookworm simulator

Prepared 2026-09-27. This is the current simulator handoff; older `codex.md`
describes historical live-TAS work and contains stale branch/task information.

## Mission and user intent

Build an in-house simulator of **Bookworm Adventures Deluxe** that can predict
alternative actions offline, then validate those predictions against native game
telemetry. The user wants sustained implementation, debugging and verification,
not another synthetic demo described as a complete simulator. They have budget
available in Claude Code and explicitly requested delegation/subagents earlier.
Use parallel workers for bounded independent work, with a single integrator and
only one owner of the live game/controller/debugger.

Focus on the simulator and the telemetry needed to verify it. The existing TAS
runner is a useful action executor and observation source. Preserve it; avoid
unrelated architecture rewrites, portfolio edits, or model-provider work.

**Truth at handoff:** deterministic synthetic encounters/campaigns work; some
native RNG/picker primitives have independent native-instruction verification.
There is no verified complete native encounter, full native checkpoint restore,
or full native campaign simulator yet. Do not treat prior milestone language as
proof that enemy AI/effects/progression/native RNG scheduling are complete.

## Repository and operating boundaries

- Repo: `https://github.com/Rohi0109/bw-tas`; local remote is **`tas`**, not `origin`.
- Workspace: `/home/rnadgir/Bookworm-google`; active branch at handoff is `main`.
- The last capture milestone before this handoff is `70b4cbc`. Read current
  `git log` for the handoff commit and any later changes.
- User has previously authorized implementation, tests, commits and pushing to
  their repository. Use focused commits; push validated milestones. Never force
  push or overwrite unrelated work.
- Check for `AGENTS.md`/`CLAUDE.md` and current working changes before editing.
  There was no applicable `AGENTS.md` found in the prior work.
- Normal installation: `runtime/deluxe-modded/`; normal Wine prefix:
  `runtime/wineprefix/`. Preserve both and their profiles.
- Capture installation: `runtime/experiments/sim-capture-v1/`; copied prefix:
  `runtime/experiments/sim-capture-prefix/`. Both exist locally and are ignored by Git.
- Never launch two input controllers against one window. Check processes before
  launching. At handoff preparation, no game, GDB, or TAS controller was running.
- Do not take screenshots without asking. Existing work used text telemetry and
  window metadata, not screenshots. Watchdogs can keep screenshots disabled.
- Do not use normal `--new-run` blindly in an experiment: `speedrun/new_run.py`
  hardcodes normal profile/log paths. It can reset the wrong profile. Make paths
  explicit or use a separately prepared test profile in the copied prefix.
- Do not weaken system-wide ptrace settings. Debug a process you launch under a
  supported parent/child relationship. No root/system setting changes are needed
  for the standalone native instruction probe.
- Keep proprietary EXE/PAK bytes, saves, full campaign logs, generated traces and
  screenshots out of Git. Commit tooling, hashes and minimal permitted fixtures.
- `/tmp` artifacts and optional environments may disappear between sessions.
  Store meaningful run evidence under an ignored, uniquely named runtime directory.

## Read these first

1. `speedrun/SIMULATOR.md`: current fidelity ledger and rule-recovery findings.
2. `speedrun/SIMULATOR_REVIEW.md`: executed validation and checkpoint defects fixed.
3. `speedrun/NATIVE_CAPTURE.md`: capture tooling, probe commands, limitations.
4. `speedrun/CAMPAIGN_SIMULATOR.md`: exact synthetic phase order and unsupported rules.
5. `speedrun/NATIVE_RNG.md`, `NATIVE_PICKER.md`, `NATIVE_DAMAGE.md`: evidence boundaries.
6. Actual implementation/tests named below. Docs are guides; inspect code and rerun
   checks before reporting a result.

## What exists and what it actually proves

| Component | Files | Current evidence / limit |
| --- | --- | --- |
| Native engine RNG | `speedrun/native_rng.py`, `tests/test_native_rng.py` | Exact 624-word engine stream and restore, independently checked against EXE instructions. Not CRT/Lua/QRand state. |
| Letter picker | `native_letter_picker.py`, `verify_native_picker.py`, `verify_native_eligibility.py` | Tables, weight/selection and eligibility helper verified independently. Full native tile-presence projection, insertion order, Lua frequency conversion and shared draw schedule not verified. |
| Damage stages | `native_damage_model.py`, associated tests | Word tier/base/gem arithmetic recovered; five nonlethal plain native fixtures. Gem outcomes, status/equipment order and enemy damage pipeline incomplete. |
| Old passive harness | `scenario_simulator.py` | Supplied refills against passive target; deliberately not predictive native simulation. |
| Seeded encounter | `offline_combat.py`, `examples/seeded_combat.json` | Generated refills, plain-word choice, constant retaliation, checkpoint replay. Explicit hypothetical scheduling. |
| Campaign harness | `campaign_simulator.py`, `examples/campaign.json` | Urgency choice, six simplified effects, configured rewards/encounters, explicit phase draw counts. Reports `native_parity: false`. |
| RNG schedule replay | `native_picker_replay.py` | Replays explicit pick/other-draw events, not inferred gameplay schedule. |
| Source inventory | `simulator_sources.py` | EXE/PAK/member hashes, manifest mismatches, reset-hook presence. Presence is not execution proof. |
| Native debugger capture | `automation/capture_native_rng*.py` | Draw entry/return snapshots and caller/thread. Capture verifier refuses discontinuities. Full-turn Lua/RNG correlation missing. |
| Native instruction probe | `automation/rng_capture_probe.s` | Freestanding x86 process executes EXE seed/draw bytes without Wine/libc. This is not a game encounter. |
| Scalar Lua capture | `automation/lua_hook/DumpSimulationState.lua`, `prepare_sim_capture.py` | Compiled and staged successfully; runtime execution still unconfirmed. Emits attack counters and selected effect scalars; flags effect queues unsupported. |

Campaign-specific caveats: per-owner effect expiry is an explicit approximation;
a one-turn player shield can expire before enemy retaliation. Counter increments
on skipped turns, refill after lethal words, stacked effects, reward timing and
extra RNG phase counts are scenario policies. Enemy-specific CanAttack overrides,
chance/resistance, gems, inventory, boss phases, save commits and book unlocks are
not modeled. Do not use training enemies as native roster entries.

## Verification already executed — rerun, do not merely repeat claims

The most recent full speedrun suite before this handoff ran **350 tests: 347
passed, three optional native-emulation tests skipped** under system Python.
Seven RNG tests, including those three, previously passed in an optional Unicorn
environment. Independent checks also completed:

- 1,300 native weight checks + 2,876 selection checks: zero mismatches.
- 655 native eligibility-helper checks: zero mismatches; C++ helpers are stubbed
  and full board projection is outside that check.
- 700 draws with complete before/after state captured from a freestanding native
  instruction process: replay matched, including a twist boundary.
- During handoff preparation, both pre-draw-start and first-draw hardware-gate
  modes were rerun: 700 draws matched in each mode. This validates the last GDB
  gate-handling patch on the probe, not on a live Wine encounter. The full suite
  was also rerun: 350 total, 347 passed, three skipped.
- Actual campaign CLI: three-turn example equals one turn plus two resumed turns,
  comparing complete checkpoint and concatenated event trace.

These numbers have separate scopes. None proves native enemy turns or campaigns.
Expected argparse errors may appear in passing tests that exercise invalid CLI
arguments. Report test process exit status, total, pass/skip counts and scope.

```sh
git status --short
git log -8 --oneline
PYTHONPATH=speedrun python3 -m unittest discover -s speedrun/tests -q
PYTHONPATH=automation python3 -m unittest automation/test_watchdog.py automation/test_local_watchdog.py automation/test_telemetry_progress.py automation/test_local_worker.py -q
git diff --check
```

For native oracles, follow `NATIVE_CAPTURE.md` and `NATIVE_RNG.md`. An optional
venv previously lived at `/tmp/bwa-sim-native-oracle` with `unicorn==2.1.4`; check
before using it. `speedrun/pyproject.toml` requests Python 3.13, while most prior
tests also ran on system Python 3.12. Record the interpreter actually used.

## Exact native evidence and pitfalls

Pinned normal EXE SHA-256:

```text
7fa527a59ff1108b98b0d18b0625d280029c0fd6c5fb3f91bb2f168b95968c67
```

Useful virtual addresses for this build only:

| Address | Meaning |
| --- | --- |
| `0x5ab440` | Engine seed routine, 82 bytes; seed supplied in EAX |
| `0x5ab4b0` | Engine NextRand entry, 257-byte routine |
| `0x5ab5b0` | NextRand return instruction; result in EAX |
| `0x767030` | 624 unsigned state words |
| `0x7679f0` | RNG cursor |
| `0x72f914` | Twist table |
| `0x4770d0` | Letter picker |
| `0x476d90` | Eligibility helper |
| `0x6c2770`, `0x6c27d8` | Letter weights, count categories |

Seed zero maps to `0x1105`; output masks to 31 bits, not a right shift. Shared
cosmetic/gameplay consumers make a correct seed insufficient for rack prediction.

Read actual installed members from `.tas-original-main.pak` for rule recovery.
`extracted/base/` is an archived web build and differs from installed Deluxe.
Verify source/member hashes for every port. Current experiment PAKs may differ
from old manifests; an experiment directory name does not establish reseeding.

Useful bytecode locations (zero-based prototype indexes):

- `scripts/TileEngine.luc` 5/7: weighted word/full word damage.
- `scripts/attacks/AttackBaseClass.luc` 5/6: base CanAttack/GetUrgency.
- `scripts/common.luc` 31: UrgencyChooser.
- `scripts/creatures/CreatureBaseClass.luc` 28/44/45: selection, buffer and HP.
- `scripts/BattleEngine.luc` 25/26/41: round/state transitions.
- `scripts/effects/*`: queues, start/end/use-dependent expiry, merging, resistance.

Decoder warning: readable disassembly can mislabel operands/opcodes. In actual
instructions, table key/left arithmetic operand is F15, value/right is F6;
CALL argument count is F15, result count F6. Custom opcode 46 is used for FLOOR;
the transcoder deliberately substitutes non-executable decompiler placeholders
for some operations. Do not execute transcoded scripts as a faithful game VM.
Review semantics against native handlers and known fixtures before porting rules.

Other traps: `AUTOMATION_DEFEATED` indicates enemy identity change, not save commit;
save_writer currently writes zero potion inventory; READY alone is not proof an
attack fully resolved. Historical board matches reused observed replacement
letters and are not independent refill predictions.

## Unfinished live capture experiment: resume here

The isolated game copy and Wine prefix were prepared. No normal profile reset
was performed, no live TAS controller was started, and no screenshot was taken.

1. A direct isolated Wine launch with a process-local `PR_SET_PTRACER` opt-in
   started the game, but sibling GDB attach failed with `ptrace: Inappropriate
   ioctl for device`. The hook is not a proven attachment solution. Host
   `ptrace_scope` was 1. Do not change that globally.
2. The launched isolated process was terminated, then GDB was used as launch parent.
   GDB followed exec into Wine's `i386-unix/wine-preloader`; an 800x600 game client
   appeared inside the Wine desktop. The first-draw hardware gate had not fired
   when this task pivoted to handoff. No successful live draw trace was produced.
3. Parent-launch configuration used `starti`, `set follow-fork-mode child`, and
   `hbreak *0x5ab4b0`, then `continue`. Wine SIGSYS/SIGSEGV were passed through
   without stopping during that experiment. Treat this as an investigative setup,
   not a production launcher; verify signal handling and do not hide real crashes.
4. Window title **`Bookworm Adventures Deluxe 1.0 `** identifies the actual client.
   Broad `Bookworm` can select **`BookwormDeluxeTAS - Wine Desktop`** instead.
   Use exact-enough title plus PID/window ownership checks. X11Keyboard's
   `_size` takes a window argument. Inspect window metadata without screenshots.
5. The last GDB patch handles entry at the first-draw gate: delete the old gate,
   install capture breakpoints, manually collect entry state if PC already equals
   NextRand entry. Otherwise the first return is unpaired. Test both launch modes
   on the freestanding probe before attempting Wine again.
6. The parent-launch attempt did not redirect game stdout into a durable Lua log.
   Add explicit separate GDB/game log handling and bounded cleanup in the launcher.
7. Do not reuse old PIDs from the conversation. Inspect current processes. At
   handoff preparation there were none to stop. `/tmp` trial files were absent.

The original probe-only validation was followed by the live launch above, but no
encounter/draw alignment was validated. This handoff records that later attempt.

## Priority implementation plan and acceptance gates

### P0 — Make native capture reliable and bounded

Build a reproducible launch harness around the staged install and separate prefix.
It must own only its own processes, preserve the normal installation, log build
identity, refuse duplicate controllers, and always detach/clean up on timeout or
error. Give it explicit output directory, maximum draws/attacks, and wall-time
limit. No open-ended full campaign while debugging startup.

Finish a supported debugger-parent Wine launch or another narrowly scoped capture
mechanism after investigating actual failure evidence. Do not assume that enabling
ptrace in a wrapper survives Wine's loader behavior. Keep the original seeded
native-instruction probe as a control.

**Gate:** capture at least 700 real-game engine draws with complete footer and
zero replay divergence; preserve EXE/PAK hashes and the launch command. Separately
confirm the Lua scalar hook executes without errors. These are still primitive
and instrumentation checks, not an encounter parity claim.

### P1 — Establish a shared native attack boundary

Define a stable `(build, session, encounter-instance, attack-id)` identity. Emit
native draw-index boundary markers before submission and after resolution. Prefer
an explicit bridge/shared counter or native callback hook over matching wall clocks.
Investigate the native Lua print binding/callback entry if useful, but validate ABI
and avoid injecting unguarded machine code. Record seeds/state resets as events.

Add a parser that handles actual and literal escaped newlines, Wine console
redraws, duplicate records, conflicting IDs, truncated records and session restarts.
Raw capture stays immutable; malformed or ambiguous turns are quarantined.

**Gate:** one word's selected tile path, damage stages, ordered RNG interval and
after-state all share an unambiguous identity. Repeated log blocks cannot become
extra attacks. Test missing/duplicate/out-of-order data explicitly.

### P2 — Complete the minimum state for one plain encounter

Start with a build-pinned enemy with simple direct damage, no treasures, gems,
status effects, potions, boss phases or tutorial side effects. Inspect the actual
definition; Trojan Spearman has a simple DamageEffect candidate but do not assume
its HP/progression data without extraction.

Capture full rack identity/attributes, selected slots, both combatants' HP and
damage buffers, offense/defense, attack list/counters/current move, phase/ownership,
and every RNG stream the encounter actually touches. Add post-turn state, not
just pre-submit scalars. Any hidden queue or unmodeled state rejects eligibility.

Establish reproducible starting state: either a verified full snapshot/restore
mechanism, or a bounded deterministic startup with evidence for every relevant
state component. A copied save plus engine seed is NOT a full checkpoint. If only
primitive replay is possible, label its scope and continue restoring missing state.

**Gate:** at least three same-state/same-action trials yield identical ordered
gameplay events and after-state, or a precise documented source of nondeterminism.
Do not mask differences by replacing predicted states with observations.

### P3 — Predict one full plain turn independently

Create a native fixture schema with provenance, initial state, action and observed
events/after-state. Simulator inputs are initial state and action ONLY. Observed
refills, enemy choice, damage or final RNG state must not leak into prediction.
Explicit recorded draw schedules may be a intermediate primitive test mode, but
must be labeled teacher-forced and excluded from full-turn parity totals.

Implement the actual order of compaction, tile registration, refill, shared RNG
consumption, attack selection, damage, retaliation and terminal handling. Include
tile flags and callback effects; picker correctness alone does not establish refill.
Compare event-by-event and stop at the first differing field with both values.

**Gate:** independent held-out plain-turn fixtures match every scoped field and
final RNG state; then repeat for an alternative legal word from the same restored
state. Matching the original action alone is insufficient for route optimization.

### P4 — Port native enemy AI and effects incrementally

Replace declarative approximations with build-pinned native rules. Extract roster
definitions and per-enemy CanAttack overrides. Validate urgency counter timing,
priority ties, RNG consumption, no-eligible-attack behavior and resets independently.

Port effects in dependency order: direct damage/buffers → regen/DOT queues →
stun/freeze/petrify and chances → damage modifiers and use-dependent expiry →
merging/resistance/purify → gem effects and treasures. Preserve offensive/defensive
ownership, queue order, QRand state, rounding and lethal cancellation.

**Gate per mechanic:** precondition → native action → ordered effect/HP events →
expiry/after-state, with source hashes and independent fixtures. Include boundary
cases, stacking, immunity and lethal interactions. Unknown mechanics fail closed.

### P5 — Implement native progression and full checkpointing

Extract encounter rosters and actual rewards. Model boss phases, loot, XP/level-up,
inventory, treasure selection, chapter/book changes and persistence boundaries.
Keep "enemy HP reached zero", "defeated identity edge", "next encounter ready"
and "save committed" as different events. Confirm save-safe exits natively.

Checkpoint the complete simulator state and all RNG streams, effect queues,
pending events and phase ownership. Native restoration must reproduce this scope;
do not rely on the existing incomplete save_writer for full restore.

**Gate:** deterministic multi-encounter/chapter replay with no boss replay after a
verified save-safe exit; then held-out cross-book cases. Only then claim campaign
coverage, explicitly listing unsupported branches.

### P6 — Make it useful for TAS optimization

Expose stable APIs for state/action/step/checkpoint/branch and a CLI for fixture
replay, batch validation and branch comparison. Keep synthetic scenario mode
separate from native-validated mode. Produce machine-readable reports with build,
coverage denominator, first divergence, unsupported reason and evidence paths.

Use the simulator to rank candidate routes, then push commits and test a small,
bounded native run with existing telemetry. Timing requires separate measurement:
debugger-paused captures cannot validate speedrun wall time. Do not trade correctness
for simulation throughput until profiling a validated implementation.

## Suggested parallel Claude work packages

Choose the first blocker locally and delegate independent work with disjoint files.
Do not have several agents attach to the game or edit the same native hook.

| Worker | Assignment | Deliverable / boundary |
| --- | --- | --- |
| Integrator / native owner | Launch, capture ownership, causal boundary, first real encounter | Only worker controlling Wine/X11/GDB; integrate findings and keep acceptance ledger |
| Fixture/validation worker | Schema, log normalization, quarantine, first-divergence reports | Parser/verifier/tests; synthetic corruption tests explicitly labeled synthetic |
| AI/effects research worker | Recover selected enemy/effect semantics from pinned bytecode | Rule/source/member-hash notes and focused pure ports; no live input or speculative generalizations |
| State/checkpoint worker | Inventory missing state and implement lossless simulator serialization | State schema/invariants/replay tests; do not label native restore complete without native evidence |

After one plain native turn works, split enemy/effect families further. Require
workers to list changed files, commands actually run, results and remaining
uncertainties. Reuse workers' evidence; avoid multiple expensive re-investigations.
Claude budget availability is not permission to create cloud charges or external
services. Local DeepSeek is optional low-stakes assistance; its prior outputs were
unreliable and it should not be the authority on native semantics.

## Working loop, commits and completion report

1. Inspect current state and pick the next unmet acceptance gate.
2. Make the smallest implementation/fixture change that tests that gate.
3. Run focused tests and the applicable independent oracle.
4. Save raw evidence under a unique ignored runtime run directory; reference its
   hashes in a compact committed validation summary where appropriate.
5. Run the full relevant suite after integration; report failures/skips honestly.
6. Commit/push a reviewable milestone; update `SIMULATOR.md` and a short progress
   log with what changed, what was independently verified, and what remains.
7. Continue useful independent work if a live test blocks. Ask only for genuinely
   missing information or a required user action; explain the concrete blocker.

Do not mark the project complete because synthetic tests pass or a model generated
a plausible explanation. Final acceptance is held-out native differential replay,
alternative-action validation, and explicitly measured coverage of mechanics and
progression. The user should be able to reproduce the result from documented
commands and see the first mismatch without reading a long assistant conversation.

## Paste this into Claude Code

> Read `CLAUDE_SIM_HANDOFF.md` and the linked simulator/capture docs, then inspect
> the current branch and working tree. Your objective is a native-validated internal
> Bookworm Adventures Deluxe simulator, not additional synthetic demonstrations.
> Start at the earliest unmet gate: finish isolated live capture, align native RNG
> draws with attack IDs, capture complete plain-encounter state, and implement
> first-divergence differential replay without using observed outcomes as inputs.
> Use parallel subagents for independent bounded tasks and one live-process owner.
> Preserve normal game/profile data, avoid screenshots, and do not weaken global
> ptrace settings. Run real tests, record evidence/provenance and unsupported cases,
> commit and push validated milestones to `tas`, and keep progressing through AI,
> effects, progression and RNG scheduling until the documented acceptance gates
> are satisfied or a concrete external blocker requires my input. Never describe
> scenario rules or primitive-only checks as full native-game parity.
