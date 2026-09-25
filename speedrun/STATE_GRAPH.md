# Deterministic graph experiments

The graph builder imports native-acknowledged, structurally usable Book 1
Chapter 1–4 transitions. It preserves competing successors for the same visible
state and ordered tile action. Duplicate records do not create repeat evidence.
All current edges remain observations: neither RNG state nor game ticks is in
the existing capture, and hidden enemy state is incomplete.

Build a report with a new output filename:

```sh
PYTHONPATH=speedrun python3 speedrun/state_graph.py --output runtime/experiments/my-graph.json
```

Initial import: 44 visible states, 22 state/action edges, all single-run
observations. This is a partial graph; encounter transitions and menu resets
are excluded. It must not be used as a shortest-path oracle yet.

## Native RNG findings

### One-shot manipulation reconnaissance (2026-09-13)

The captured `engine-seed-game/tas-live.log` segment starting at 11:47:05
already clears Chapter 1 in five attacks. The first two-hit target is Chapter 2
Cyclops Warrior: `EDFU/EPAT/AWHO/GAUE`, 5 HP, Bow of Zyx; WHEEPED deals
2.75, followed by FERMATA. Start the experiment on the preceding Angry Ram
(`JAAN/UAHG/AIUO/GNTE`, 3 HP, baseline JAUNTING), seeking a successor rack
with a native-confirmed Cyclops Warrior one-shot. These are historical samples,
not a claim about the currently running game.

Static inspection of the installed Lua bytecode identifies shared-engine RNG
consumers in word-presentation particles (`TileEngine`, source line 572), Lex
attack setup (`LexDefaultAttack`, line 36), submission banter (`BattleEngine`,
line 1710), and conditional screen-shake updates (`BattleEngine`, line 2411).
The scramble path also calls `NextRand` (`BattleEngine`, line 3280). This makes
alternative words/tile paths the first low-overhead experimental lever: they
change survivors/refill count, and presentation may also change random draws.
Waiting during an active random-consuming animation is a secondary hypothesis;
idle waiting is NOT established to advance RNG. Scramble must include its
native time and combat costs. Static call sites alone do not prove a useful
or repeatable manipulation.

Installation check: the current `engine-seed-game/main.pak` has no
`AutomationResetAttackRng` method, and its current `lua.log` has no reset
markers. Do not assume this installation still provides per-submission resets
just because of its directory name. Restore the experimental hook in a new,
isolated build and verify markers before collecting controlled comparisons;
do not overwrite a running installation or its logs.

First acceptance target: reproduce the same pre-Ram state, branch one legal
lethal word/path, and verify the resulting Warrior rack and one-shot in three
fresh trials. Compare the complete Ram-through-Warrior interval, including
manipulation overhead. Direct seed changes are laboratory controls, not proof
of a route achievable through ordinary inputs. A successful lab branch still
needs validation without forced per-submission reseeding.

### Refill trace (2026-09-13)

The three per-submission reset trials still diverged because the reset targets
the CRT/Lua random stream, while the native letter picker uses a separate
engine stream. This is a confirmed distinction in the executable call graph;
timing-dependent consumption may also exist but is not needed to explain why
the previous reset failed to control letter generation.

- The native letter-selection code consults Lua `GetExtraLetterFreq` at
  `0x4775ce`, builds adjusted letter weights, and calls `0x5b0020` at
  `0x4776f2`. It takes the returned value modulo the total weight, then walks
  cumulative weights to choose a letter.
- The Lua binding for `sexy.NextRand` is registered with function `0x4990c0`.
  That function also calls `0x5b0020` (at `0x4990cd`).
- `0x5b0020` jumps to `0x5ab4a0`, which jumps to `0x5ab4b0`. This generator
  uses a 624-word array at `0x767030` and a cursor at `0x7679f0`. Its seed
  routine is `0x5ab440`, with the seed passed in EAX; zero substitutes `0x1105`.
  State initialization uses multiplier `0x6c078965`, followed by twist and
  tempering operations consistent with MT19937. Output is masked to 31 bits.
- This path never calls CRT `rand` at `0x66699b`. Resetting `math.randomseed`
  therefore does not reset the engine stream used by the letter picker.
- Word-presentation particle Lua code also uses `sexy.NextRand`, so engine RNG
  state can be shared with cosmetic work. Reseeding it at submission still
  needs a repeat test; isolating refill draws is a stronger experimental control.

The previous `QRand`-only explanation is also insufficient: Lua QRand retains
weight and hit history, but this refill path chooses letters in native code.
An engine RNG snapshot requires the entire 624-word array plus its cursor,
not just a seed. The picker also consults existing letter counts and treasure
frequency modifiers, so those inputs belong in a refill model.

The subsequent engine experiment is installed under `engine-seed-game`, now
selected by `rng-game` and `rng-tas`. It redirects only the Lua randomseed
binding's call at `0x4ce285` to an argument adapter in validated padding at
`0x5ab492`, then tail-calls `0x5ab440`. The adapter loads the stack seed into
EAX and preserves the existing caller stack cleanup. The executable hash guard
restricts this patch to the known fixed-seed experimental build.

Reset markers now read `AUTOMATION_RNG_RESET=<id>|1|submit|engine|E`.
The comparison tool distinguishes engine and CRT policies. Previous copies
and trial logs remain in their original directories. This build still resets
at submission; cosmetic RNG calls after that point may affect refill draws.
Build/disassembly verification is complete; live repetition remains necessary.

## First controlled branch tests

The validated three-run baseline has the exact Goat state fingerprint
`cc66eaf3d9ba1afabc6c`: `ZANY/PSAE/FNUR/SITL`, 3 HP, Bow of Zyx, plain tiles.
All three choose FRENZY and refill to `SAEE/ISAU/PNUM/SITL`. `NAZIFY` and
`ZANILY` are legal six-tile, 3.5-damage lethal alternatives in the same
excellent animation class. Exact-state overrides are saved under
`runtime/experiments/engine-seed-game/branches/`. Try one per fresh run with:

```sh
just rng-tas --book1-overrides runtime/experiments/engine-seed-game/branches/NAZIFY.json
```

Then repeat the same override three times before comparing refills. The
alternate choices are experiment branches only; no normal solver policy was
changed.

```sh
python3 automation/prepare_attack_rng_experiment.py --engine-rng --output runtime/experiments/engine-seed-game
```

Executable SHA-256:
`7fa527a59ff1108b98b0d18b0625d280029c0fd6c5fb3f91bb2f168b95968c67`.
In this build, `srand` is at VA `0x66698e` and `rand` at `0x66699b`.
Both obtain CRT thread data from `0x67256e`; the RNG state is at offset `0x14`.
The recurrence is `(state * 214013 + 2531011) mod 2^32`, returning
`(state >> 16) & 32767`. Native seed call sites include `0x45c547`,
`0x4ce285`, and `0x59b7a9`. Consequently, the old claim that no Lua seed calls
means a process always uses seed 1 is not established for this build.

`automation/prepare_rng_experiment.py` creates a fresh installation copy with
the native srand argument forced to 1, guarded by the executable hash and
instruction signature. Its manifest records original and patched hashes and
bytes. It never launches the game. The seed patch is experimental, not a
normal TAS change. It does not capture or restore the current RNG state.

```sh
python3 automation/prepare_rng_experiment.py --output runtime/experiments/fixed-seed-game
```

## First replay experiment

The current `rng-game`/`rng-tas` commands target `attack-seed-game`, which adds
`math.randomseed(1)` after submission telemetry and immediately before the
original SubmitTiles body. The older fixed-seed copy and captures are retained.
Build it once with `python3 automation/prepare_attack_rng_experiment.py`.
`AUTOMATION_RNG_RESET=<attack_id>|1|submit|E` confirms the reset returned;
the runner includes this marker in both outcome record types.
Compare repeats using:

```sh
PYTHONPATH=speedrun python3 speedrun/compare_rng_trials.py runtime/experiments/attack-seed-game/tas-timing.jsonl
```

Use fresh processes/profiles with the same choices for three trials. This is
an experiment to test whether per-submission reseeding removes the observed
refill divergence, not a complete battle checkpoint/restore implementation.

Launch with `just rng-game`, then run `just rng-tas` in another terminal.
The runner's `--experiment` mode generates a unique session ID, records actual
executable/PAK hashes under `fixed-seed-game/sessions`, and disables the race
timer and race-record updates. Chapter context falls back to the enemy roster
when Lua omits it. IDs identify runner sessions, not independently restored
game processes; restarting the runner alone is not a fresh replay trial.
Existing records without IDs remain unchanged and are excluded by the importer.

Use a separate Wine prefix and disposable profile, since another installation
directory alone does not isolate ProgramData saves. A fresh process and fresh
profile are required for each initial trial; an in-game profile reset alone
does not reset CRT state. Replay the same startup inputs and first ordinary
fight three times. Record executable/PAK hashes, complete ordered actions,
native attack IDs, and the resulting rack and combat state. Compare them using
the graph importer. Vary input timing in a separate trial to expose random calls
that depend on animation updates.

Before certifying edges, native instrumentation still needs to capture seeding
and random calls with thread identity, authoritative game ticks, and checkpoint
identity. A full checkpoint must restore enemy AI/animation state, tile and
reward state, player state, progression, and every relevant RNG stream. A BWA
save alone is not such a checkpoint.

Do not substitute historical refill letters into an alternative action. Scylla's
recorded 7 to 1.75 HP transition also disagrees with the 6.25 predicted damage;
explain enemy response/damage before using those two-hit plans as executable
routes. Once repeats agree, branch one action at a time and validate promising
routes in the regular TAS installation.
