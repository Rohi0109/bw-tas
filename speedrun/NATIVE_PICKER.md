# Native letter picker kernels

`native_letter_picker.py` ports the integer weight and selection kernels from
the same executable pinned in [NATIVE_RNG.md](NATIVE_RNG.md).

| Native location | Recovered behavior |
| --- | --- |
| `0x6c2770` | 26 base letter weights, A–Z |
| `0x6c27d8` | 26 count limits/categories |
| `0x4775fe` | Add integer-converted `GetExtraLetterFreq` result |
| `0x477605` | Optional caller flag zeros count-two letters outside category four |
| `0x47763b` | Category three/count two subtracts truncated weight/3 |
| `0x477667` | Category four/count two subtracts truncated weight/6; count three subtracts weight/4 |
| `0x4776f7` | Draw modulo total weight |
| `0x477710` | Select first strict cumulative boundary |

The public API requires explicit eligible letters, counts, integer extra
frequencies and the caller flag. Unsupported negative/overflowing weight domains
and zero totals raise an error. Eligibility is not inferred from the weights.

## Independent verification

```sh
# Requires optional Unicorn and the pinned local EXE, not a running game.
PYTHONPATH=speedrun python3 speedrun/verify_native_picker.py \
  runtime/deluxe-modded/BookwormAdventures.exe
```

The verifier checks both tables against EXE bytes, then runs the original weight
and selection blocks in isolated x86 emulation. On 2026-09-26 it completed
1,300 weight cases and 2,876 cumulative-boundary/modulo cases with zero mismatches.
Tests supply inputs directly to these kernels; Lua callbacks and eligibility
construction are not executed. No game asset or process is modified.

## Candidate eligibility

`load_exclusions` recovers 41 strings from the pinned EXE's static initializers
(`0x6af700` onward, target objects `0x725e90`–`0x72630c`).
`eligible_letters` applies count caps, row/column exclusions and the quota helper;
`pick_letter` composes eligibility, weighting and one engine RNG draw. Missing
tiles are explicit `*` characters; deciding which native tiles count as present
remains the caller's responsibility.

```sh
PYTHONPATH=speedrun python3 speedrun/verify_native_eligibility.py \
  runtime/deluxe-modded/BookwormAdventures.exe
```

On 2026-09-26 the eligibility helper matched 655 native x86 checks with zero
mismatches, including a hole at every position in all exclusion strings. This
oracle stubs C++ string copying/comparison, vector size and stack-cookie checks;
it executes the original filtering/quota instructions. Full board-to-pattern
projection is not emulated by this check.

## Remaining work before rack parity

- Independently validate board-to-pattern projection at `0x477470` and native
  tile-presence semantics. Y counts as a vowel; count caps precede weighting.
- Recover exact Lua extra-frequency conversion and treasure modifications.
- Distinguish callers passing flag zero (`0x47796f`) and one (`0x477f3c`).
- Recover tile insertion traversal and count updates between multiple draws.
- Capture or reproduce all interleaved RNG consumers. Choosing letters directly
  from a seed is not sufficient to predict a native submission's next rack.

Keep these kernel checks separate from full-picker, refill and game-turn parity.

## Explicit schedule replay

`native_picker_replay.py` composes picker calls with explicit intervening engine
draws. It imports/exports all 624 RNG words and the cursor, supports checkpoint
resume, and compares optional observed letters/draws without correcting the
prediction. Every call requires its board, frequency adjustments and caller flag.
It does not infer the missing gameplay schedule.

```sh
PYTHONPATH=speedrun python3 speedrun/native_picker_replay.py schedule.json \
  --executable runtime/deluxe-modded/BookwormAdventures.exe --output replay.json
```

The input model is `explicit-picker-schedule-v1`, with `initial_rng` containing
`words` and `cursor`, and `events` containing either `{ "kind": "draws", "count": 2 }`
or a `pick` with `board`, 26 integer `extras`, and boolean `restrict_duplicates`.
Picks optionally carry `expected_letter` and `expected_draw` for comparison.
Output is created exclusively so existing evidence cannot be overwritten.

Further caller evidence: `0x477f10` traverses a linked list (not a vector), picks
with flag one, then invokes Lua `ChangeLetter` (`0x6ca510`) before advancing to
the next entry. The tile constructor invokes `RegisterTile` (`0x6ca5f0`) after
the flag-zero pick. Thus callback effects must be accounted for between calls;
these disassemblies alone do not establish a gravity/refill traversal order.
