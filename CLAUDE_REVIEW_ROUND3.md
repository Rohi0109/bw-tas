# Review of 9e6e40b

Much better: two reproduced blockers remain before a bounded live capture.
This file records review findings, not implementation fixes.

## Remaining blockers

1. **High: fixture validation accepts impossible/incomplete state.**
   `speedrun/native_fixture.py:171` checks shallow types instead of the actual
   board/action/combat/RNG schema. A fixture with `board=[None]`, action
   `NOT_A_WORD`, combat state `?`, and `rng_snapshot={"words": [], "cursor": -999}`
   was classified eligible when otherwise required metadata and numeric HP fields
   were present. Require the supported complete encounter schema, an actual legal
   selected action/path, 624 unsigned 32-bit RNG words, and cursor 0..624. Require
   sufficient observed after-state for the claimed comparison scope as well.
   Prefer reusing validated state/RNG contracts over another shallow parallel schema.
   Unsupported or uncaptured hidden state must prevent full-turn eligibility.

2. **High: actual console prompt framing is still silently lost.**
   `automation/capture_log_parser.py:60` strips leading controls/ANSI but not the
   printable `> ` prompt before the backspace/space sequences. The following
   input still yields zero parsed records and zero quarantines:

   ```python
   ['> \b \b\b \bAUTOMATION_SIM_BEGIN=1|E\\r\\n'
    '> \b \b\b \bAUTOMATION_SIM_END=1|E\\r\\n']
   ```

   Normalize the real observed prompt framing before parsing logical records.
   Use a real log excerpt with creature/attack fields in regression tests, not
   only synthetic leading-backspace or ANSI examples. Recognized malformed
   telemetry must be quarantined, never silently dropped or marked valid.

## Remaining verification gap

The new process cleanup test starts a process and calls `_killpg_safe` directly.
It does not execute the launcher's cleanup control flow with a parent that exits
and a stubborn descendant that remains. It also signals immediately after Popen,
before confirming that the child installed its SIGTERM handler; a zombie can
still make a process group appear alive. Add an explicit readiness handshake
and test the real launcher path with a controlled parent/child fixture. Separately
verify Wine descendants that leave the original process group. Do not claim live
Wine cleanup is proven by the helper test.

## Confirmed improvements

- A sole eligible non-due attack now consumes the weighted-choice RNG draw.
- Normal project installation/prefix paths are explicitly rejected.
- Process-group cleanup escalates to SIGKILL after a grace period when the group
  still exists after GDB exits.
- Invalid HP values and malformed in-block records are rejected.

## Executed results

- Speedrun suite: **452 tests run, 449 passed, three skipped**.
- Parser/launcher automation suite: **38 tests passed**.
- Additional fixture and console-prompt reproductions above still fail the
  intended eligibility/quarantine requirements.
- No live game or Wine capture was launched during this review.

## Claude continuation

> Fix the two reproduced blockers and close the launcher-cleanup verification
> gap before declaring this round complete. Add tests that fail on 9e6e40b and
> pass after the fixes. Validate real state structure and actual captured console
> framing, not merely the literal bad values listed in this review. Then run the
> relevant suites and record exact results. Proceed to one bounded isolated live
> capture only after these gates pass, preserving normal profiles and recording
> build identity and first-divergence replay evidence. Push focused tested commits.

The original mission and operating boundaries remain in `CLAUDE_SIM_HANDOFF.md`.
