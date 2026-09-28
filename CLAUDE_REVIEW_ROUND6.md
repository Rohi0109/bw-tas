# Review of 5d248f0

Both round 5 reproductions are fixed: conflicting build/session/encounter
provenance and attack/counter length mismatches are rejected. The added
validation checks attack entries for integer min/max fields.

## Remaining integration finding: mixed attack field names lose AI state

The updated positive encounter fixture renames mMin/mMax to min/max but leaves
mState, mAlreadyPerformed, and mDamage unchanged. The schema accepts this hybrid
as eligible, whereas native_enemy_ai reads state and already_performed. Thus
captured flags can be silently ignored when an accepted attack is passed to AI.
The Lua hook still emits all fields with their m-prefixed names.

Reproduction on this commit:

```sh
PYTHONPATH=speedrun:speedrun/tests python3 - <<'PY'
from test_native_fixture import _minimal_fixture
from native_fixture import validate_fixture
from native_enemy_ai import choose_attack
f = _minimal_fixture()
a = {'min': 1, 'max': 1, 'mAlreadyPerformed': True,
     'mDamage': 1.0, 'mState': 0}
f['pre_submit']['enemy_attacks'] = [a]
f['pre_submit']['enemy_counters'] = [1]
print(validate_fixture(f).value, choose_attack([a], [1]))
a['already_performed'] = a.pop('mAlreadyPerformed')
print(choose_attack([a], [1]))
PY
```

Output is `eligible 0`, then `None`. This demonstrates disagreement with the
current AI contract; it does not establish the native meaning of that flag.

Define one canonical attack representation and explicitly convert hook fields
to it. Reject mixed/unknown representations rather than silently defaulting
missing flags. Preserve or quarantine numeric native state until its mapping is
known. Add a parser-to-state-to-AI regression test covering attack flags, not
just schema-only synthetic tests. Avoid fixing only the positive fixture names
while leaving the accepted representation ambiguous.

## Validation

- Speedrun suite: **473 tests run, 470 passed, 3 skipped** in an isolated worktree.
- Explicitly reproduced rejection of all three conflicting provenance fields
  and the previous counter mismatch.
- Automation was unchanged and was not rerun this round.
- No live game/Wine capture ran; full-turn native parity remains unverified.

After aligning the capture and replay contracts, continue the bounded isolated
capture work in `CLAUDE_SIM_HANDOFF.md`. The previous findings are closed; this
review identifies the next concrete integration issue, not a request for broad
refactoring.
