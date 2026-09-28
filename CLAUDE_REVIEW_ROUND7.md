# Review of c005b45

The mixed-name reproduction from round 6 is now rejected, and typed Lua
mAlreadyPerformed is translated correctly. The actual capture-to-AI boundary
still needs integration coverage; the new tests call normalise_attack directly
with hand-built typed dictionaries, not parser output.

## Findings

1. **High: complete hook attacks are rejected.** DumpSimulationState.lua emits
   mRateCounter for every attack. normalise_attack does not map it and raises
   `unknown m-prefixed attack field: 'mRateCounter'`. The revised positive
   encounter fixture removes this field, masking the mismatch. Support the
   complete hook representation and explicitly reconcile its counter with the
   parallel enemy_counters array; reject conflicts rather than dropping data.

2. **High: unknown native attack state remains eligible.** mState is preserved
   as native_state_raw, but build_encounter_state does not add an unsupported
   reason for its unconfirmed meaning. A snapshot with mState=999 is ELIGIBLE
   with an empty unsupported_fields list. The AI ignores native_state_raw.
   Preserve the evidence and mark unhandled state unsupported until a supported
   mapping is established; storage alone does not make the state replayable.

The parser returns strings, including `false`, and the normalizer only renames
keys. There is no demonstrated typed conversion in these new tests. A string
`false` remains truthy to choose_attack, and parsed min/max strings fail the
encounter integer checks. Define an explicit conversion boundary (including
nil/invalid values) and test it rather than relying on Python-typed examples.

## Reproductions

From the repository root:

```sh
PYTHONPATH=speedrun:speedrun/tests python3 - <<'PY'
from native_enemy_ai import normalise_attack
from encounter_state import build_encounter_state, encounter_eligibility
from test_encounter_state import _plain_data
hook = dict(mMin=1, mMax=1, mRateCounter=1, mDamage=2,
            mState=0, mAlreadyPerformed=False)
try:
    normalise_attack(hook)
except ValueError as exc:
    print(exc)
data = _plain_data()
data['enemy_attacks'][0]['mState'] = 999
state = build_encounter_state(data)
print(encounter_eligibility(state).value, state.unsupported_fields)
PY
```

Output: unknown mRateCounter error, then `eligible []`.

Acceptance: add one test starting with complete hook-format log lines, passing
through parse_sim_log, typed conversion, encounter validation, and AI. Cover
true/false, mRateCounter alignment, and unsupported native state. Do not remove
emitted fields from the test to make it pass. Keep native semantic uncertainty
explicit; this is contract integration work, not proof of the native AI rules.

## Verification

- Speedrun: **484 tests run, 481 passed, 3 skipped**, isolated worktree at c005b45.
- Additional reproductions confirmed full-hook rejection, parser string values,
  truthiness of string false in AI, and unknown-state eligibility.
- Automation unchanged; full automation suite not rerun this round.
- No live game/Wine capture. Full native turn parity remains unverified.

Continue with the bounded isolated capture in CLAUDE_SIM_HANDOFF.md once this
capture-to-replay boundary works with complete records.
