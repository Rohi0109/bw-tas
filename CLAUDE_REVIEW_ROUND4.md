# Review of d7ea3ec

The console framing blocker is fixed. Cleanup coverage now exercises the
production cleanup function with a readiness handshake. Fixture eligibility
remains incomplete; passing unit tests do not establish native turn parity.
This commit contains review findings only.

## Remaining high-priority finding: eligibility still accepts impossible or incomplete turns

`speedrun/native_fixture.py` validates the board's formatting and the action's
uppercase spelling independently. It never checks whether the board can supply
the selected word. The positive fixture in
`speedrun/tests/test_native_fixture.py::_minimal_fixture` uses board
`ABCD/EFGH/IJKL/MNOP` with action `TEST`, although neither T nor S occurs on it.
The validator returns `ELIGIBLE`. It also accepts seventeen As on that board.

Reproduction from the repository root:

```sh
PYTHONPATH=speedrun:speedrun/tests python3 - <<'PY'
from test_native_fixture import _minimal_fixture
from native_fixture import validate_fixture
for word in ('TEST', 'A' * 17):
    fixture = _minimal_fixture()
    fixture['pre_submit']['selected_action'] = word
    print(word, validate_fixture(fixture).value)
PY
```

Both print `eligible` on d7ea3ec.

The same fixture has no enemy identity, attack counters, combat modifiers,
gem/power state, or explicit captured effect state. Removing `combat_state`
from required fields does not supply those missing inputs. Its observed state
contains only two HP values, so it cannot establish board refill or RNG-state
parity. An empty caller-supplied `unsupported_state` list is insufficient
evidence that the missing state is supported and captured.

These are the action/state requirements already requested in round 3, not
additional scope. Recommended acceptance criteria:

- Validate the selected action against the captured board and supported game
  rules. Capture selected tile indices when needed to disambiguate tile state;
  reject missing letters, tile reuse, and impossible lengths. Do not impose
  adjacency rules unless the game requires them.
- Require a validated supported encounter snapshot for full-turn eligibility,
  reusing the existing encounter-state contract where appropriate. Derive
  unsupported or incomplete status from captured state rather than trusting
  an empty list supplied by the caller.
- Require observed after-state sufficient for the claimed comparison, including
  board and RNG for full-turn replay. HP-only records may be useful partial
  observations, but must not count toward full-turn parity.
- Replace the impossible positive fixture with a valid one. Add negative tests
  for impossible actions, omitted combat state, and HP-only full-turn records.

## Confirmed fixes and verification

- The real prompt/backspace framing regression includes creature and attack
  fields and passes.
- The original malformed RNG snapshot now raises ValueError; board formatting
  and RNG shape/range checks are substantially improved.
- Cleanup tests wait for the SIGTERM handler and call `_cleanup_process_group`.
  This verifies same-group escalation with a mocked exited parent; actual Wine
  descendants, particularly those leaving the group, remain unverified.
- Speedrun: **458 tests run, 455 passed, 3 skipped**.
- All automation tests: **66 tests run, 65 passed, 1 skipped**.
- Suites ran in an isolated worktree at d7ea3ec. No live game/Wine capture ran.

After correcting the eligibility contract, proceed with the bounded isolated
capture and first-divergence evidence described in `CLAUDE_SIM_HANDOFF.md`.
Do not claim complete native simulator fidelity from these unit tests alone.
