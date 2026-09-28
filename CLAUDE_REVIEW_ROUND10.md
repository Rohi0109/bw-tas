# Review of 0990d65

The production assembly module now exists and invokes parser/conversion/fixture
validation. However, its contracts do not yet match captured data, and it can
replace missing or unsupported evidence with eligible synthetic state.

## Findings

1. **High: actual capture cannot populate the required snapshot.** The creature
   map expects player_hp/enemy_hp/enemy_name, but DumpSimulationState.lua emits
   mHealth/mMaxHealth/mName/mDamageBuffer/mOffenseBonusPct/mState. Actual mHealth
   and mName fields are ignored. Board/RNG/gems/powers are expected as tuple keys
   not supplied by that hook; the documented extra input is not used to provide
   these captured components. Also, the parser rejects a dimensionless BOARD
   row (id|board|E), while assembly expects the dimensionless ('BOARD',) key.
   Define the real capture sources and join contract rather than inventing
   field names only used by tests. Map native scalar semantics explicitly.

2. **High: incomplete/unsupported evidence is silently replaced.** A single RNG
   word plus cursor becomes 624 words via zero-fill. Missing mRateCounter becomes
   zero. EFFECT rows are ignored and both effect lists are set empty; the hook
   only emits UNSUPPORTED for effect queues, not every nonempty effect. Tile
   arrays check count but not exact indices and fill missing indices with plain
   defaults. Require complete indexed data and explicit absence evidence;
   preserve effects as unsupported. Missing capture is not a safe default.

3. **High: player attacks enter enemy_attacks.** group_log_attacks groups both
   owners, then assembly strips owner/key metadata and assigns every attack to
   the enemy. Filter by owner and preserve captured attack identity. Stable
   string sorting alone is not evidence of native attack ordering.

4. **High: boundary/provenance annotations are lost.** Every parsed block is
   assembled using the same extra.attack_id, selected_action, RNG interval and
   observed state; rec.attack_id is never checked or used. This can relabel
   different turns as one. extra.teacher_forced and extra.unsupported_state are
   also discarded and replaced with False/empty. Bind supplementary evidence to
   each captured boundary, reject mismatches, and preserve classification flags.

## Reproduced evidence

Run from the repository root:

```sh
PYTHONPATH=speedrun:speedrun/tests python3 - <<'PY'
from test_assemble_captures import _make_fields, _minimal_attack, _EXTRA
from assemble_captures import assemble_encounter_from_fields
from native_fixture import validate_fixture
for case in ('partial_rng', 'effect', 'player_attack', 'teacher_forced'):
    attack = _minimal_attack()
    attack.pop('mState')  # isolate each finding from the known state-map limitation
    fields = _make_fields([attack])
    extra = dict(_EXTRA)
    if case == 'partial_rng':
        for i in range(1, 624):
            del fields[('ENGINE_RNG', 'words', str(i))]
    if case == 'effect':
        fields[('EFFECT', 'player', '1', 'mDuration')] = '5'
    if case == 'player_attack':
        for key, value in attack.items():
            fields[('ATTACK', 'player', '0', key)] = value
    if case == 'teacher_forced':
        extra.update(teacher_forced=True, unsupported_state=['uncaptured'])
    fixture = assemble_encounter_from_fields(fields, extra)
    print(case, validate_fixture(fixture).value,
          len(fixture['pre_submit']['enemy_attacks']),
          fixture['pre_submit']['player_effects'], fixture['teacher_forced'])
PY
```

All four print eligible. The player-attack case contains two enemy attacks;
the effect case has an empty player effect list; teacher_forced becomes False.

## Test gap and next acceptance criteria

The log helper supplies attack rows only. Its test asserts eligibility is not
eligible, so an incomplete-state error passes without verifying unsupported
state propagation. Add a real success-path assembly test using hook-format
creature and attack rows plus explicitly joined captured board/RNG data. Assert
an actual fixture and the exact unsupported classification/reason, not merely
`!= eligible`. Add negative cases for each finding above, two distinct attack
IDs, both owners, and effects without an UNSUPPORTED marker.

Keep invalid, incomplete, unsupported, and eligible outcomes distinguishable.
Continue bounded isolated capture after this boundary works; do not claim
native parity based on these synthetic assembly tests.

## Executed checks

- **527 speedrun tests run: 524 passed, 3 skipped**, isolated worktree at 0990d65.
- Independently reproduced all four eligible cases above and confirmed actual
  mHealth/mName inputs produce no mapped health/name fields.
- Automation implementation unchanged; full automation suite not rerun.
- No live game/Wine capture. This review changes documentation only.
