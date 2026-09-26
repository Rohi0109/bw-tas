# In-house simulator

Goal: reproduce the installed Deluxe build closely enough to evaluate alternative
actions offline, then validate promising routes against the native game.
Full-game fidelity is not established. Existing telemetry omits hidden state,
and historical successor racks cannot be reused as alternative-action outcomes.

## Run the first offline harness

```sh
PYTHONPATH=speedrun python3 speedrun/scenario_simulator.py \
  speedrun/examples/passive_scenario.json --output /tmp/bwa-scenario.json
```

Use a new output filename for each report. No game, Wine, X11, or installed game
assets are needed for this synthetic example. The supplied word allowlist defines
legal actions; Q represents a single QU tile. Both strategies start from the same
immutable state and their own cursor into the supplied hypothetical letter stream.

This first model compares `shortest-lethal` and `max-damage` against a passive
target using the existing damage/ranking code and column gravity. It excludes
enemy responses and stops at lethal damage before rewards or encounter changes.
Only plain selectable racks and no treasure/Bow of Zyx are accepted. Refills are
explicit scenario inputs, not predictions. Attack-time proxies exclude enemy
turns, menus and loading. Exhausted refills, missing words and attack limits are
reported separately from defeat. Reports include full action/state traces and
assumptions. This is a decision test harness, not a native battle emulator.

## Fidelity ledger

| Workstream | Existing evidence | Missing implementation/evidence | Acceptance gate |
| --- | --- | --- | --- |
| Build identity | Experiment manifests and executable hashes; extracted Lua assets | Tie every recovered rule to the installed Deluxe executable/PAK, not archived web assets | Reproducible hash manifest for every reference fixture |
| RNG and refill | Native MT-style engine call path documented in STATE_GRAPH; CRT RNG implementation is separate | Complete RNG snapshot, native recurrence validation, call ordering, weights, treasure/history effects | Match raw RNG draws and complete racks across independent restored trials and alternative actions |
| Board mutation | Column gravity reproduces structurally filtered observations | Native refill order, duplicate tile paths, QU, blocked/infected tiles, gem creation and persistence | Independent before/action/after fixtures with every tile attribute checked |
| Damage | Native tier table, Bow override, quarter-heart rounding and regression examples | Enemy defenses/immunities, gem quantization, powered damage, remaining treasures | Match native pre-submit damage and attributable HP edges across held-out enemies/equipment |
| Enemy turns and statuses | Enemy Lua assets, player status flags and partial telemetry | AI state, move selection, direct/DOT damage attribution, healing, status tick order and expiry | Match ordered event stream and both combatants' HP/status after every turn |
| Encounter/progression | Route rules, boss save-safety observations, map events | Rewards, treasure selection, boss phases, checkpoint persistence, book transitions | Full state agrees at each boundary; defeated bosses never replay after a save-safe exit |
| Timing and ownership | Wall-clock attack/READY/menu traces and empirical animation classes | Native ticks, update ordering, input acceptance, cosmetic RNG consumers | Reproduce ownership edges and tick counts; wall-time benchmarks remain separate |
| Checkpoint/restore | Profiles and visible-state fingerprints | Hidden enemy/Lua/animation state and all RNG streams | Restoring a checkpoint reproduces identical event/state hashes for the same ordered actions |
| Dataset provenance | Audits retain run IDs, native attack IDs, source lines and source hashes | Causal alignment for older logs; representative independent holdouts | Quarantine ambiguous records; split by run/build/start state; report unsupported coverage and mismatches |

## Implementation gates

Implemented primitive checks: [engine RNG](NATIVE_RNG.md),
[letter eligibility/weight/selection kernels](NATIVE_PICKER.md) now have
independent x86 comparisons. [Staged damage](NATIVE_DAMAGE.md) ports word/gem
formulas separately from enemy resolution. Complete board projection, refill
ordering, draw scheduling and combat remain open.

Inventory an installation without extracting or modifying it:

```sh
python3 speedrun/simulator_sources.py --source runtime/deluxe-modded \
  --output /tmp/bwa-source-inventory.json
```

The report includes EXE/PAK hashes, all script-member hashes, experiment-manifest
mismatches and reset-hook string presence. Presence is not execution proof.

1. Inventory sources and record evidence, unknowns and exact-build identity.
2. Recover and test small pure mechanics against independent native fixtures.
3. Compose a deterministic turn engine with explicit state and RNG snapshots.
4. Compare full event traces, not just end HP. Stop at the first unsupported
   mechanic; do not silently approximate it in a native-fidelity run.
5. Add encounter progression and timing only after combat parity. Evaluate
   alternative routes on held-out checkpoints, then confirm them natively.

## Investigation results — 2026-09-26

Three parallel read-only investigations covered RNG/refill, combat, and
progression/timing. Findings are evidence for the work queue, not parity claims.
Runtime paths below are local evidence and are not distributed with the repo.

### RNG/refill: first priority

- Static inspection corroborated the current executable's picker call at
  `0x4776f2` into the shared engine generator via `0x5b0020`. The engine uses
  624 words plus a cursor, MT-style operations, a 31-bit mask and seed-zero
  substitution `0x1105`. `bwakit/game/bwa_rng.py` models the separate CRT stream.
- The picker applies `GetExtraLetterFreq`, conditional count/category adjustments,
  modulo-total and cumulative selection. Independent fixed letter probabilities
  are insufficient. Recover tables at `0x6c2770` / `0x6c27d8`, count updates,
  rounding, flags and refill traversal from this exact build.
- Current `runtime/experiments/engine-seed-game/main.pak` hash begins
  `f9b18a29`; its manifest records `4682aa68`. Its current BattleEngine entry
  lacks `AutomationResetAttackRng`, and its current Lua log has no reset markers.
  The EXE matches its manifest, but the combined build is not the recorded build.
  Partition trials by actual EXE/PAK identity before comparing them.
- Sampled `extracted/` web bytecode differs from installed Deluxe members. Pin
  member hashes before porting any rule. Cosmetic and combat code share
  `NextRand`; exact ordered draw consumption is still missing.

Offline next step: recover an exact generator and picker from pinned binaries,
then compare against isolated native-code execution. Test zero seed, twist
boundaries, snapshot/restore, weight boundaries, duplicate counts, treasures,
multi-slot traversal and final RNG state. Generator parity alone is not refill
parity; refill parity alone is not whole-game parity.

### Progression, state and dataset coverage

- `automation/lua_hook/DumpDialogs.lua` emits `AUTOMATION_DEFEATED` on enemy-name
  change, not on a disk-save commit. Treat it as an identity edge.
- `bwakit/game/save/save_writer.py` writes a zero-potion block. It cannot serve
  as a complete checkpoint round-trip. The visible `DeluxeState` also lacks
  enemy AI state, effect durations, pending events and RNG snapshots.
- The stored native damage audit has 30 eligible HP matches, only five of them
  nonlethal. Historical replay has 82/91 HP matches; the 91 board matches use
  observed, structurally prefiltered refills. These are different evidence sets.
- The current normal timing file scan found 9,205 lines, one malformed record,
  and 3,425 records without outer book/chapter context. Records span all 30
  chapters, but raw coverage does not establish causal or independent trials.
- Existing menu trace: 100 cycles, 99 complete, 100 dialog timeouts and zero
  dialog acknowledgements. Wall-clock completion cannot certify native menu
  ownership or exact tick timing.

Offline next step: refresh the corpus audit across all books, retain malformed
and ambiguous cases in quarantine, join by build/session/native attack identity,
and extract encounter-boundary fixtures separately. Add chapter and encounter
instance to same-encounter validation. Never pool builds silently.

### Combat and effect ordering

- Native `TileEngine.GetFullWordValue` evaluates tile bonuses against base word
  damage. Current `DumpBoard.lua` evaluates `ApplyBonus(letterPower)`, and the
  solver sums those stored values. Gem bonuses cannot generally be treated as
  candidate-independent constants. Emerald also uses an enemy gem modifier.
- The nine historical HP mismatches comprise four Circe cases overpredicted by
  2.5 and five Sea Elemental/Kraken/Sea Witch cases overpredicted by 1.0. The
  implicated classes reference regeneration. Healing is a hypothesis for those
  residuals, not attributable proof; do not subtract a blanket offset.
- The preserved Deluxe `.tas-original-main.pak` contains useful sources:
  `TileEngine.luc` prototypes 5/7 (damage), `EmeraldTile.luc` 6/7 (bonus/heal),
  `CreatureBaseClass.luc` 28/44/45 (attack selection/damage), and
  `BattleEngine.luc` 25/26/41 (round and state transitions). Prototype indexes
  are zero-based. Effect scripts contain DOT, skip-turn, resistance, multiplier
  expiry and merging behavior that the current state model does not carry.
- The bytecode disassembly renderer's table operands disagree with its decoding
  helpers. Validate operand interpretation against known methods/constants
  before translating new rules; readable disassembly alone is insufficient.
- `luc_transcode.py` deliberately substitutes markers for custom FLOOR and
  table-iteration instructions to aid decompilation. Its output is not a
  runnable replacement for the native VM. A headless script executor needs
  independently tested opcode semantics and native object/API implementations.

Offline next step: separate weighted value, base damage, tile bonuses, enemy
modifiers and HP application. Build explicit turn/effect state with injected
attack choices first. Differential cases must cover one gem at multiple tiers,
quarter-rounding boundaries, resistance, duplicate-letter tile selection,
regeneration after direct damage, DOT edges, freeze turn skipping, multiplier
expiry, lethal cancellation of retaliation, and tile attributes through gravity.

Passing a test against a formula reused from the solver is internal consistency,
not independent validation. A deterministic hypothetical stream is not proof of
native RNG parity. Report coverage denominators, unsupported cases and divergent
trials alongside successes; no blanket residual corrections to make traces fit.

Related evidence: [STATE_GRAPH](STATE_GRAPH.md),
[TRANSITION_BASELINE](TRANSITION_BASELINE.md),
[native damage audit](audit_native_damage.py), and
[transition replay](simulate_transitions.py).
