# Review of cbdf389

Round 4's concrete reproductions are fixed: unavailable letters and overlong
actions are rejected, required combat snapshot fields are enforced, and HP-only
observations are rejected. Unsupported status now incorporates the encounter
snapshot. These are substantive improvements.

## Remaining findings

1. **High: conflicting snapshot provenance is accepted.** In
   `speedrun/native_fixture.py::_validate_pre_submit`, `setdefault` preserves a
   nested build/session/encounter identity that conflicts with the outer fixture.
   `validate_build_identity` checks only the outer build. Consequently a snapshot
   from a different build or session can be classified eligible under the outer
   provenance. Reject conflicts, or disallow nested provenance and use the outer
   identity as the sole source; do not silently relabel conflicting evidence.

2. **Medium: attack/counter alignment is not validated.** The reused
   `build_encounter_state` contract accepts `enemy_attacks=[]` alongside
   `enemy_counters=[1]`. These arrays are documented as parallel, but the fixture
   is eligible despite their mismatch. Validate equal lengths and the supported
   attack-entry structure before admitting the snapshot to replay.

Reproduce both from the repository root:

```sh
PYTHONPATH=speedrun:speedrun/tests python3 - <<'PY'
from test_native_fixture import _minimal_fixture
from native_fixture import validate_fixture
for key, value in [
    ('session_id', 'different-session'),
    ('build', {'BookwormAdventures.exe': 'c' * 64, 'main.pak': 'd' * 64}),
    ('enemy_counters', [1]),
]:
    fixture = _minimal_fixture()
    fixture['pre_submit'][key] = value
    print(key, validate_fixture(fixture).value)
PY
```

All three print `eligible` on cbdf389. Add targeted regression tests for these
cases, including conflicting encounter_instance and both mismatch directions.

## Executed validation

- Speedrun suite: **464 tests run, 461 passed, 3 skipped**, in an isolated worktree.
- Explicitly confirmed rejection of TEST on ABCD/EFGH/IJKL/MNOP, seventeen As,
  missing enemy_attacks/player_effects, and HP-only observed state.
- Automation code is unchanged in this commit; its suite was not rerun this
  round (previous review: 65 passed, 1 skipped).
- No game/Wine capture was launched. Native full-turn parity remains unproven.

Fix these focused validation gaps, then continue the isolated capture and
first-divergence replay work in `CLAUDE_SIM_HANDOFF.md`. Schema acceptance is
only an admission check, not proof that captured turns match the simulator.
