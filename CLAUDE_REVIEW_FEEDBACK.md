# Claude simulator review feedback

Reviewed the four commits after `9761a2f`, through `c2380a5`.

**Useful scaffolding, but it is not ready for native validation yet.**
These findings are from code inspection and executed reproductions. This file
records the review; it does not implement the fixes.

## Findings

1. **High: corrupted telemetry passes quarantine.** Wrong attack IDs, conflicting
   HP values, and unsupported effect queues were all classified as "good" in
   reproduced cases. Console-prefixed, escaped log blocks can disappear entirely.
   See `automation/capture_log_parser.py`, especially field handling around
   lines 139–158. Parse errors and ID mismatches must affect eligibility rather
   than being discarded with internal metadata. Conflicting values must be
   identified by field identity, not treated as separate valid keys.

2. **High: empty fixtures qualify as eligible.** `pre_submit={}` and `observed={}`
   pass validation without a board, action, combat state, or RNG snapshot. This
   could make future validation results misleading. See
   `speedrun/native_fixture.py`, especially `_validate_pre_submit` and
   `_validate_observed`. Require the actual state/action schema and reject missing
   or ambiguous capture evidence before granting native replay eligibility.

3. **High: launcher isolation is not enforced.** The launcher accepts the normal
   installation and normal Wine prefix despite claiming they are protected.
   Its duplicate-process check only covers the selected EXE path. See
   `automation/launch_capture.py` around lines 80–116. Resolve and validate paths,
   protect normal profiles, and prevent conflicting session/controller ownership.

4. **High: cleanup does not reliably own the whole process tree.** Timeout handling
   kills GDB, not explicitly its Wine descendants; successful capture detaches
   the game. The claimed bounded session can leave processes running. See
   `automation/launch_capture.py` around lines 143–165 and the detach path in
   `automation/launch_capture_gdb.py`. Prove cleanup on success, failure, timeout,
   and interruption while preserving unrelated processes.

5. **Medium: the new AI module loses previously recovered behavior.** It collapses
   weighted urgency into three levels, always selects the lowest-index tie, and
   consumes no RNG. It is not integrated into the simulator yet, so this is a
   defect to resolve before integration rather than a current campaign regression.
   See `speedrun/native_enemy_ai.py`. Preserve the recovered weighted urgency,
   due-attack handling, and draw consumption; validate against native evidence
   rather than adding more approximations.

## Executed checks

- Speedrun suite: **423 tests run; 420 passed, three skipped**.
- New parser/launcher automation tests: **28 passed**.
- Additional reproductions:
  - Wrong row attack ID: one good record, zero quarantined.
  - Unsupported effect queue: one good record, zero quarantined.
  - Conflicting HP values: one good record, zero quarantined.
  - Console-prefixed escaped block: zero good records, zero quarantined.
  - Empty pre-submit/observed dictionaries: fixture classified eligible.
  - Two due attacks: new AI selected index zero without consuming RNG; existing
    campaign chooser selected index one when supplied draw one.

Passing tests do not negate these failures. Add regression tests that exercise
them. The launcher tests use mocks and do not establish that a real Wine launch,
native capture, or process-tree cleanup works. No new live game trial was run
during this review.

## Instructions for Claude Code

> Fix these review findings before adding more mechanics. Preserve weighted
> native urgency and RNG consumption, reject incomplete/contradictory fixtures,
> test real console formatting, and enforce isolated process ownership. Then
> demonstrate one bounded live capture with replay evidence. Don't count mock
> launcher tests as proof the Wine capture works.

Continue following `CLAUDE_SIM_HANDOFF.md`: use one live-process owner, preserve
the normal installation/profile, avoid screenshots without permission, and keep
native fidelity claims tied to independent evidence. Commit focused fixes,
record the commands and outcomes actually observed, and push tested milestones.
