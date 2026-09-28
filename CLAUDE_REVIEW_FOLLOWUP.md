# Follow-up review of Claude's fixes

Reviewed commit `6de6e28` against `CLAUDE_REVIEW_FEEDBACK.md`.

**Better, but not fully fixed. Do not claim all five findings are resolved yet.**
This file records review findings and requested fixes; it does not implement them.

## Remaining issues

1. **High: the normal project profile is still unprotected.**
   `automation/launch_capture.py:108` blocks the environment/default Wine prefix,
   typically `~/.wine`, but accepts this repository's actual normal prefix,
   `/home/rnadgir/Bookworm-google/runtime/wineprefix`. A mocked launch reproduction
   confirmed that this path reaches `Popen`. No actual game was launched.
   Explicitly reject the resolved normal project prefix and installation, including
   symlink aliases. Validate staged provenance rather than only marker existence.
   Add a regression test using the repository's normal prefix, not only `~/.wine`.

2. **High: incomplete or invalid fixtures still qualify as eligible.**
   `speedrun/native_fixture.py:152` requires only player/enemy HP fields. A fixture
   with `NaN` and negative pre-submit HP, plus string/None observed HP, was classified
   `eligible`. It also lacked board, selected action, combat state and RNG snapshot.
   Require the actual state/action schema for full-turn eligibility, validate finite
   nonnegative numeric fields on both sides, and reject missing/ambiguous evidence.
   A structurally valid partial observation must not become a full-turn fixture.

3. **High: real console formatting is still dropped and malformed rows escape quarantine.**
   `automation/capture_log_parser.py:50` replaces literal `\\n` without splitting
   the resulting records or handling literal `\\r` and console prompt/backspace
   prefixes. A console-prefixed escaped block produced zero good records and zero
   quarantine records. Around line 148, a malformed field missing its `|E` terminator
   is silently ignored; the surrounding block was then classified good.
   Normalize actual observed console framing, split logical records, and quarantine
   recognized but malformed telemetry. Test prompt/backspace prefixes, literal
   `\\r\\n`, multiple records per input line, and missing terminators.

4. **High for RNG fidelity: a sole non-due attack still skips a draw.**
   `speedrun/native_enemy_ai.py:119` returns early whenever only one attack is
   eligible. For one attack with `min=0`, `max=-1`, counter 1, the new chooser
   consumed zero draws, while the existing recovered weighted chooser consumed
   `ai-weighted`. Only the sole *due* attack has the recovered no-draw shortcut.
   Remove the unconditional single-eligible shortcut, preserve the due branch,
   and test both selected attack and final RNG state/draw count.

5. **Medium: process-group cleanup is improved but not verified complete.**
   `automation/launch_capture.py:205` sends only SIGTERM when GDB has already
   exited. A remaining descendant that ignores SIGTERM has no verified exit or
   SIGKILL escalation. Timeout escalation also depends on GDB staying alive, not
   whether its descendants survived. Check owned descendants/group after the grace
   period and escalate as needed; never kill unrelated processes. Test a real
   temporary parent/child fixture where the parent exits and the child ignores
   SIGTERM. Separately validate Wine children that leave the original process group.

## Confirmed improvements

- Wrong embedded attack IDs now quarantine the block.
- Unsupported effect queues now quarantine the block.
- Conflicting field values are detected by canonical field identity.
- Weighted urgency and randomized due-attack ties are restored, apart from the
  single-eligible draw omission above.
- The launcher creates a separate process group and attempts group cleanup.

## Checks actually executed during this review

- Speedrun suite: **443 tests run; 440 passed, three skipped**.
- Parser/launcher automation suite: **33 passed**.
- Wrong-ID and unsupported-state reproductions: zero good, one quarantined each.
- Escaped console block reproduction: zero good, zero quarantined (still wrong).
- Malformed field reproduction: one good, zero quarantined (still wrong).
- Invalid HP and incomplete-state fixture: classified eligible (still wrong).
- Sole non-due AI choice: new chooser zero draws; baseline one weighted draw.
- Normal repository Wine prefix: reached mocked launch (still wrong).

The process-cleanup finding is based on code inspection; no live Wine trial or
stubborn-child cleanup test was executed in this review. Passing mocked tests do
not prove native launch, capture, or cleanup. No implementation changes were made
as part of the review.

## Instructions for Claude Code

> The first fixes improved the implementation, but the five findings above remain
> open in whole or in part. Fix these exact failure cases before adding mechanics
> or declaring native capture ready. Add regression tests that fail on `6de6e28`,
> then pass with your changes. Enforce the actual normal-profile boundary, require
> complete native fixtures, parse real console framing without silently losing
> records, preserve the sole non-due RNG draw, and demonstrate owned-process cleanup
> with a real child-process fixture. Rerun the relevant suites and report actual
> results. After these gates pass, attempt one bounded isolated live capture and
> preserve replay evidence. Do not count mocks or synthetic fixtures as proof of
> native-game parity. Commit and push focused, tested fixes.
