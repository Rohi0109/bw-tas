# Review of 518542f

The non-finite damage finding is closed. Conversion and canonical encounter
validation both reject NaN, positive infinity, and negative infinity. No new
blocker was found in that fix.

## Remaining integration work from round 8

The commit adds assemble_hook_attacks, but it is only called by tests. Its
production definition wraps convert_hook_attack_types; no capture/fixture/replay
entry point invokes it. The parser likewise has no production caller in the
reviewed Python code. This is an available helper, not a wired capture path.

The new log-lines test is useful: it runs the real parser, groups one attack,
converts it, normalises names, and calls choose_attack. However, grouping lives
inside the test, and the path skips build_encounter_state and its eligibility
check. It therefore cannot establish that the production path carries counter
conflicts, quarantine, or unsupported native state correctly.

Next implementation should connect the components through a real entry point:

1. Read a captured log, partition quarantined records, and preserve reasons.
2. Group attacks by owner and attack key in production code, preserving a stable
   association between each attack and its captured counter.
3. Convert types, combine with explicitly supplied captured board/RNG/provenance
   and combat state, and call encounter/fixture validation. Missing captured
   data must remain incomplete; do not synthesize it to obtain eligibility.
4. Preserve unsupported state and prevent unsupported records from entering
   native full-turn parity totals.
5. Exercise that same entry point in tests with complete log records, both
   boolean flags, counter conflicts, quarantined blocks, and unmapped mState.

Use the smallest appropriate CLI or existing pipeline integration. Do not add
another wrapper with only test callers and call the production wiring complete.
Once connected, continue the bounded isolated capture and first-divergence
evidence work in CLAUDE_SIM_HANDOFF.md. Capturing unsupported evidence is useful;
it must retain that classification until the native state mapping is established.

## Executed validation

- Speedrun suite: **501 tests run, 498 passed, 3 skipped**, isolated worktree at
  518542f. The new parser-to-AI test passed as part of this suite.
- Independent negative checks rejected all three non-finite damage values at
  both conversion and canonical encounter validation boundaries.
- Searched production Python callers for parser, assembly, and conversion;
  confirmed the integration gap above.
- Automation code unchanged; its full suite was not rerun this round.
- No live game/Wine capture was launched. Full native turn parity remains
  unverified. This review changes documentation only.
