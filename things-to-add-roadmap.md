# TAS issues from `things to add`

This is the normalized work list. An item is **fixed** only after its stated
native acceptance check passes; a Python unit test alone is not sufficient.

| Priority | Issue | Current finding | Fix | Acceptance check |
|---|---|---|---|---|
| P0 | Rack/Attack misses and retries | **Fixed and Book 1 accepted.** Lua now emits selection state and `AUTOMATION_ATTACK_READY` only after a complete valid word survives the long-word interrupt plus 15 clean native updates. The fresh acceptance run recorded exactly one native submission for every Chapter 1 enemy, including Trojan Captain, with no missing acknowledgement timeout. | Keep selection separate from Attack; advance only Lua-authorized long-word pulses and click Attack exclusively on `AUTOMATION_ATTACK_READY`. | Passed for fresh Chapter 1. Continue watching later status/potion encounters for regressions; intentionally invalid words remain a separate result. |
| P0 | Purify recovery selects a stray tile | Code-fixed, live verification pending. The runner clicked `(400, 480)` after Lua had already reported incapacitation inactive, when that coordinate belonged to the rack again. | Never click the former overlay after the inactive edge. Click only while the native overlay predicate is active, then require a newer READY sequence. | Force petrify/freeze, Purify, and confirm the first subsequent native submitted word exactly matches the solver word/path with no extra selected letter. |
| P0 | Steel Stymphalian → Nemean Lion reset blocked by level-up | Code-fixed, live verification pending. `levelup` was excluded from the post-reset recovery allowlist. | Allow a genuine level-up Continue pulse to clear the blocker, then replay the full menu-reset sequence. | Kill Steel Stymphalian while leveling up; observe Continue, a repeated reset, and Nemean Lion READY without manual input. |
| P1 | Chapter 4 proactive Scramble | Open; trigger is underspecified. Current code scrambles only when there is no playable word. | Record the exact Book/chapter/enemy and compare attack-now versus Scramble from the same deterministic state before adding a route-specific action. | Two same-seed branches show the forced Scramble saves time and does not worsen the following rack; then add an exact-state or exact-encounter rule. |
| P1 | Slow Book 1→2 and Book 2→3 transitions | Open optimization; correctness path exists. | Timestamp native save-ready, menu, Adventure, chapter-map, `start-game`, dialogue, and first READY edges. Remove only measured dead time and use acknowledgements instead of sleeps. | Three clean transitions per boundary with no retries; median transition time improves and progress/treasures remain intact. |
| P1 | Gems may persist across chapters | Unverified. Existing logs show gems across enemy changes, not enough to prove chapter-boundary persistence. | Log gem identity/position on the final pre-boss READY, immediately after the boss, and first READY of the next chapter. Compare carried gem IDs or exact tile state. | At least two controlled boundaries agree. Only then value surviving gems in final-boss word selection. |
| P1 | Boss immunity to three-letter words | Unverified except Mama Roc, which is already modeled. Medusa's AVO/JAR attempts lacked native submission acknowledgement, so they currently indicate the rack race rather than immunity. | Use native submission plus HP delta: no submission = controller failure; accepted submission plus zero damage/native rejection = enemy rule. Extract the matching creature rule before filtering candidates. | One accepted three-letter and one accepted four-plus-letter control per suspected boss, or a directly identified native rule, with regression fixtures. |

## Recently closed supporting issues

- Weighted word length is now read from the native BattleEngine on every
  accepted attack. Live samples proved that Deluxe rounds half-up rather than
  flooring; the optimizer was corrected in commit `8e22e0d`.
- A native `start-game` action now clears stale boss/menu/treasure transition
  blockers, preventing the Chapter 2 Cassandra suppression loop (`0dff893`).
- Power-Up is now detected from the native status-effect set. The runner waits
  for the effect and input ownership to remain stable before selecting the
  finishing word, and it will not consume health potions first (`a8a91a7`).
- Fresh-profile creation now lets Wine finish receiving focus before its first
  main-menu click; `just new-run` passed from the normal welcome screen
  (`921e587`).
