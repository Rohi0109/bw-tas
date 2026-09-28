# Review of c4a56c1 (including dummy commit 0f716bd)

Round 7's concrete findings are resolved. mRateCounter maps correctly and
conflicting counters are rejected. Unmapped native attack state now marks the
encounter unsupported. Explicit conversion handles string true/false correctly.
The dummy commit contains no additional implementation changes.

## Executed verification

- Speedrun suite: **493 tests run, 490 passed, 3 skipped**, isolated worktree at
  0f716bd.
- Manually exercised complete hook-format lines through parse_sim_log, grouping
  the attack fields, convert_hook_attack_types, build_encounter_state, and
  choose_attack. False selected attack 0; true selected none. Both encounters
  correctly remained unsupported because native attack state is unmapped.
  Calling the AI helper here checks flag plumbing, not native parity or a
  production authorization to replay unsupported encounters.
- Automation code unchanged; full automation suite not rerun this round.
- No live game/Wine capture was launched.

## Remaining medium-priority validation finding

Non-finite damage is accepted by the new conversion helper and the encounter
validator. This reproduction prints eligible for nan, inf, and -inf:

```sh
PYTHONPATH=speedrun:speedrun/tests python3 - <<'PY'
from native_enemy_ai import convert_hook_attack_types
from encounter_state import build_encounter_state, encounter_eligibility
from test_encounter_state import _plain_data
for damage in ('nan', 'inf', '-inf'):
    data = _plain_data()
    data['enemy_attacks'] = [convert_hook_attack_types({
        'min': '1', 'max': '1', 'damage': damage,
        'already_performed': 'false',
    })]
    state = build_encounter_state(data)
    print(damage, encounter_eligibility(state).value)
PY
```

Reject non-finite attack damage during conversion and canonical state validation,
so already-typed inputs cannot bypass the check. Add focused regression tests.
Do not infer a nonnegative-only rule without checking the native damage domain.

## Next milestone: connect and exercise capture

The conversion helper currently has no production callers; the added tests
start with hand-built dictionaries. Commit the complete parser-to-state test
described above and wire the conversion boundary into the actual fixture
assembly/replay path, with quarantine and unsupported status propagated. The
manual check proves the components can be composed, not that they are wired.

Then continue the bounded isolated capture in CLAUDE_SIM_HANDOFF.md. Preserve
the unknown-state evidence and report unsupported captures honestly; do not
delete native_state_raw merely to make fixtures eligible. Establish its mapping
before claiming supported native full-turn replay. Further schema-only tests
are not a substitute for captured fixture and first-divergence evidence.
