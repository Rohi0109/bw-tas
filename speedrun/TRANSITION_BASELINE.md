# Transition baseline audit

## Preloaded fresh runs

With Deluxe open at the main menu and the intended TAS profile selected:

```sh
just tas-new
# Or explicitly require the selected profile's name:
just tas-new --profile Lex10
```

This **deletes and recreates the active profile**, using the same guarded
workflow as `just new-run`. Other profiles are protected. The solver dictionary,
transition corpus, overrides, and controller are initialized before profile
confirmation; the same process and input lock continue into automation. No
separate-process startup bridge is needed. The timer still starts on the key
confirming the new profile name, so intro and gameplay are not excluded.

Fresh runs ignore older log content using the pre-confirmation log offset.
`just tas` still resumes without recreating a profile, and `just new-run` remains
available separately. Normal runner options also work with `just tas-new`.

Run from the repository root, using a new output directory:

```sh
python3 speedrun/audit_transition_corpus.py --output runtime/analysis/my-audit
PYTHONPATH=speedrun python3 -m unittest speedrun.tests.test_audit_transition_corpus
```

The audit streams existing telemetry, omits large candidate frontiers from
extracted records, and preserves original before/action/after payloads. Source
line numbers and a SHA-256 of the bytes read provide provenance. It does not
change the live runner, raw telemetry, or the live transition corpus.

Outputs:

- `observations.jsonl`: Chapter 1–4 pairs passing conservative structural checks.
- `quarantine.jsonl`: remaining Chapter 1–4 pairs, with rejection reasons.
- `report.json`: coverage through Chapter 9 and limitations.

The first audit retained 7 of 747 Chapter 1–4 transition records. The second
audit retained 91 after testing column compaction: all 84 records excluded
solely for moved unselected letters matched downward movement of surviving
letters in their original columns. Accepted records now include the survivor
source/destination mapping and observed new letters at top-of-column slots.
This validates a structural hypothesis on these examples, not the RNG that
generated new letters or an exact causal pairing for every example.

Current checks
require a newer sequence, one input attempt, finite ordered timing, a legal
tile path, net HP loss within the same encounter, and column-compacted surviving
letters. These are deliberately restrictive criteria for the first
damage/refill experiments, not a verdict that every excluded row is corrupt.
In particular, refill movement and legitimate enemy effects may explain changed
unselected letters; encounter changes need a separate route-aware validator.

Do not treat `clean` as an attack acknowledgement. The logger currently derives
it from input-attempt count. Do not rewrite missing chapter numbers into both
states: the outer chapter describes the submitted action, and a subsequent
state may belong elsewhere. Repeated observations are retained, not assumed
independent. Timing remains wall clock rather than native frame counts.

## Offline partial simulator

```sh
PYTHONPATH=speedrun python3 speedrun/simulate_transitions.py \
  --source runtime/analysis/ch1-4-baseline-audit-v2/observations.jsonl \
  --output runtime/analysis/my-simulator-report
```

This runs the current solver damage formula and column gravity with injected
observed refill letters. It does not model RNG, gem generation, enemy turns,
status changes, or animation frames. Reports preserve run/enemy/equipment/status
groups and source line numbers; existing output directories are refused.

Baseline v1: 91 observations across 21 runs, 91 board matches, only 2 HP matches.
The board result is not independent validation: the audit already selected
gravity-compatible records. The most frequent observed-minus-predicted damage
residuals are +0.75 (38 records) and +1.0 (24). Do not fit a blanket offset:
historical pairing, enemy rules, and recorded state completeness remain unverified.

New Lua events are additive; legacy acknowledgement events are unchanged:

- `AUTOMATION_ATTACK_ID=id|enemy|word|E`: SubmitTiles entry, not proof of damage.
  IDs increase within one Lua runtime and restart with the game.
- `AUTOMATION_ATTACK_HP=id|oldHP|newHP|E`: HP change of the same enemy object.
  Includes possible DOT/healing; it does not claim direct word damage.
- `AUTOMATION_READY_ATTACK=sequence|id|E`: latest submission at snapshot time,
  not proof that the attack has resolved. Zero means no submission yet.

The runner includes the latest 64 identity event lines in `native_attack_events`
on transition/kill rows. Raw Lua logs retain the full stream. Scope IDs to the
game session (and retain run provenance); never join IDs across game restarts.
Rebuild the TAS copy and restart the game to load modified Lua hooks.

Next: reconcile damage residuals against new native-ID captures before changing
the live damage model. Split validation by run and starting state rather than
randomly splitting repeated rows.

## Native damage trace

The pristine Deluxe `TileEngine.luc` methods `GetWordValue` (prototype 5)
and `GetFullWordValue` (prototype 7) establish this pipeline:

1. Sum positive `tile:ModifyValue(1 + LETTER_BONUSES[tile.mLetter])` values.
2. Round that sum and cap the tier at 16; use `gDamageByWordLength[tier - 1]`.
3. Evaluate each tile's `ApplyBonus` against **base word damage**, sum bonuses,
   apply the native bonus quantization, then add base damage and base × offense.

This is pre-enemy/status/treasure-resolution damage, not necessarily HP loss.
The damage table is supplied outside the shipped Lua definitions; its values
must be captured, not assumed from the current Python constants. Existing rack
telemetry evaluates `ApplyBonus` against intrinsic letter value instead, so its
numbers are not interchangeable with native word-damage bonuses.

`AUTOMATION_DAMAGE_TRACE=id|value|tier|base|full|offense|slots|E` now samples
the selected tiles at SubmitTiles entry, before refill can mutate tile objects.
`full` comes directly from `GetFullWordValue`; slots are a row-major selected
set, **not** the ordered spelling path. `AUTOMATION_DAMAGE_TABLE=id|values|E`
reports the 16 native table entries on first observation or change. Both events
are retained with attack identity telemetry. Legacy post-submission word values
remain for comparison; disagreement alone does not establish a letter-weight bug.

```sh
PYTHONPATH=speedrun python3 speedrun/audit_native_damage.py \
  --output runtime/analysis/my-native-damage-audit
```

After rebuilding/restarting, capture Chapters 1–4 to compare pre-submit values,
native base/full damage, and identified HP edges. Scoring constants remain
unchanged until this trace validates their replacements. No RNG calls or combat
state setters were added by the trace.

## September 11 scoring correction

The new capture supplies the native table directly: tiers 1–16 map to
`0.25, 0.25, 0.5, 0.75, 1, 1.5, 2, 2.75, 3.5, 4.5, 5.5, 6.75, 8, 9.5, 11, 13`.
The old Python mapping was one tier behind. Live scoring now uses this table,
caps weighted tiers at 16, and keeps dictionary eligibility at 3–16 rack tiles.
Suppressed tiles no longer contribute their base unit to weighted length.

`ArtemisBow.luc` assigns X/Y/Z bonuses of 1.5 when Bow of Zyx is equipped;
the solver now applies that override. Native nonlethal traces also demonstrate
floor-to-quarter HP damage, not the previous final ceiling. For example,
TRIFORIUM's raw native damage is 4.9035326130688 and its HP loss is 4.75.

Validation artifacts:

- `runtime/analysis/native-damage-sep11-before/report.json`: pre-change audit.
- `runtime/analysis/native-damage-sep11-validated/report.json`: 32 distinct IDs,
  30 eligible tier checks and 30 eligible HP checks all matching; five of these
  HP checks are nonlethal. Two attacks lack usable before-rack pairing.
- `runtime/analysis/ch1-4-simulator-sep11/report.json`: historical HP matches
  improve from 2/91 to 82/91. Those observations remain structurally filtered,
  not newly certified causal transitions. No blanket residual correction added.

Native QU words are normalized to the solver's single Q tile in the audit.
Five identified nonlethal captures are covered by regression tests. Gem bonus
scaling, other treasure overrides, powered-up damage, and enemy/healing rules
are not claimed solved. These changes update the scoring model, not dictionary
search structure, RNG prediction, or a complete multi-turn planner. No speedup
claim is made without a new timed run; restart only the runner to load Python.

## Two-hit comparison and isolated trial

```sh
PYTHONPATH=speedrun python3 speedrun/compare_two_hit_fights.py \
  --run-id 2026-09-11T14:54:23.349763+00:00 \
  --output runtime/analysis/my-two-hit-report
```

The comparison keeps runs separate and requires a structurally usable
same-enemy transition plus a matching native submission. It searches pairs of
words on supported plain racks using disjoint original tiles. Those plans are
conditional on no intervening enemy healing/tile/status effects, not full battle
simulation. No observed refill is reused for an unplayed first action. The
current timing proxy uses 10 ms per tile and empirical animation medians; it
excludes enemy turns, menus, and unmodeled presentation time.

Run 14:54:23 has four eligible first-hit transitions. None has a lethal pair
using only pre-existing surviving letters. The remaining comparisons require
new branch observations. The first-hit damage/time shortlist yields one
stronger trial: Sea Serpent `OUTRAVED` deals 3.75 rather than `VAPORED`'s 2.75,
leaving 2.25 HP rather than 3.25. Its first-hit proxy costs 0.725 s more; it only
wins if the changed second rack enables a sufficiently faster finisher. This
is a hypothesis, not a measured saving. Equal-cost/damage words can leave
different survivors, so the shortlist is not exhaustive multi-turn pruning.

The generated `trial-46-OUTRAVED.json` changes exactly one state/action and is
not auto-loaded. To test it on a replay reaching the same baseline state:

```sh
just tas --book1-overrides runtime/analysis/two-hit-run145423-v2/trial-46-OUTRAVED.json
```

No profile reset is performed by that command. If the exact fingerprint is not
reached, the override does not apply. Compare the complete Sea Serpent encounter
and its successor state, not just first-hit damage, before adopting the branch.
