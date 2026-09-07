# Bookworm Adventures TAS roadmap

An item is **fixed** only after automated tests and native game traces agree.
Timing changes are judged by clean chapter splits, not only individual input
latencies.

## Next priorities

| Priority | Work | Current evidence | Next step | Acceptance check |
|---|---|---|---|---|
| P0 | Determine why Chapter 6 drops fast tile clicks | On the latest Book 1 Chapter 6 run, the opening conversation closed cleanly and a fresh native READY arrived. Griffon accepted only **8/10** letters at both 20 ms and 40 ms, then accepted all **10/10** at 60 ms. Harpy repeated the pattern (**8/9**, **7/9**, then success at 60 ms). There is no evidence that dialogue clicked a stray rack tile. | Repeat Chapter 6 on multiple fresh runs and seeds. Log chapter/enemy, requested path length, every native selection count, per-click cadence, frame/update timing, and time since dialogue exit. Also sample the same long words in earlier chapters and Chapter 5 immediately before the boundary. Do not hardcode Chapter 6 or globally slow typing until the pattern repeats. | Classify the cause as chapter-specific, session/performance degradation, long-word cadence, or another native ownership condition using at least three comparable samples. |
| P0 | Recover immediately from partial native selection | A dropped tile currently causes the selector to wait the full eight-second native-ready timeout before the ordinary retry path runs. | Once the post-selection telemetry has settled and the native count is below the requested path length, return a structured partial-selection result immediately. Clear and retry at the next cadence without pressing Enter. Keep the last proven cadence only for the appropriate scope discovered above. | Forced partial-selection tests never submit an incomplete word and do not wait eight seconds; a live retry recovers without corrupting the rack. |
| P0 | Move chapter-boss menu exit to the earliest save-safe lethal edge | Angry Mob took 4.287 seconds from native zero HP to `BOSS_RESET_READY`. Exiting at zero HP was tested on Grim and proved unsafe: the next snapshot restored Grim at its pre-lethal **7 HP**. The runner has therefore returned to the reliable settled edge. | Timestamp the already-emitted native death-flag transitions and test the intermediate `mStateAnimsDone` edge separately. Authorize an earlier reset only after the next chapter and treasures survive repeated same-seed exits. | Repeated same-seed boss kills exit before the visible death animation completes, retain the unlocked next chapter and treasures, and never replay the defeated boss. |
| P0 | Explain and reduce the Chapter 1 gap | TAS best is **1:04.895** versus the human WR segment of **0:46.700**, or **18.195 seconds behind**. Chapter 2 is already **6.165 seconds faster** than the human segment, so word solving alone is not the main gap. | Split Chapter 1 into filename/menu, opening dialogue, PLAY, each enemy, boss reset, and Chapter 2 entry. Compare those edges with the supplied WR video. | Three clean runs identify consistent gaps and the Chapter 1 best improves without retries or unsafe clicks. |
| P0 | Shorten stun/freeze/Purify recovery | Native traces still spend several seconds on incapacitation. Purify often needs a second or third click; without it, the full overlay animation remains. | Timestamp overlay frame, potion input, status-clear, continuation ownership, and next READY. Test a selectable-tile fast path only while the native overlay owns input. | Forced stun, freeze, and petrify recover without a stray tile or unnecessary potion and improve median READY-to-READY time. |
| P0 | Make treasure selection deterministic | Treasure selection can toggle an already-selected item off because every desired slot is clicked blindly. A previous recovery produced the wrong Book 3 loadout. | Add native slot identity and selected-state telemetry, then click only the difference between current and desired selections. | Multiple initial selection states always produce the intended final inventory before Continue. |
| P1 | Optimize Power-Up policy | Solver decisions take roughly 130–185 ms; native Power-Up activation takes about **0.91 seconds**. Wolf-Man exposed that all `DamageMultiplierEffect` objects were incorrectly labeled Power-Up, including Power Down. The hook now reports the native `mMultiple`, and the solver counters Power Down when Power-Up restores a one-shot; live verification is pending. | Verify the reported down multiplier and boosted damage on Wolf-Man, then simulate attack-now versus Power-Up across deterministic states, including Power Down, Genie/Sphinx modifiers, survival, and potion opportunity cost. | Wolf-Man's down-powered nominal finisher triggers Power-Up and kills in one attack; a documented policy then beats the current route in repeatable simulation and passes live damage checks. |
| P1 | Optimize book transitions | Book 1→2 and Book 2→3 are correct but contain menu, Adventure, chapter-map, dialogue, and first-READY dead time plus occasional re-entry retries. | Timestamp every native ownership edge and replace only measured waits. Add definitive Adventure-entry acknowledgement if needed. | Three clean samples per boundary, no redundant input, and a lower median transition time with progress and treasures intact. |
| P1 | Replicate the unexpected Moxie treasure entry | After Grim in Book 3 Chapter 7, Lua emitted `AUTOMATION_MINIGAME_PROMPT=3|7|1` at **12:50:42.848**. The runner used its existing mini-game-skip action, received `minigame-callback`, and then Moxie's treasure screen opened. This has not reproduced in earlier runs, so the prompt wording/button meaning or click ownership is not yet established. | Repeat the same checkpoint without changing routing. Capture the prompt event, native chapter selection flags, exact input sent, callback, next chapter-map state, and whether Moxie's screen opens. Compare at least three occurrences and distinguish a reversed button meaning from a late/misdirected click or stale prompt event. | The behavior is reproduced and classified. Only then change routing; three follow-up runs must skip Moxie and enter the intended chapter without opening its treasure screen. |
| P1 | Evaluate Hydra per-head menu skips | The route does not deliberately reset after every Hydra head and may overkill heads. | Compare same-seed normal progression with a main-menu reset after each head; constrain head attacks to the cheapest safe lethal word. | The alternate route saves total chapter time repeatedly without losing progress or corrupting phases. |
| P1 | Chapter 4 proactive Scramble | The proposed trigger remains underspecified; current code scrambles only when no word is playable. | Capture an exact encounter/state and simulate attack-now versus Scramble from the same seed. | Two same-seed branches show a repeatable net chapter gain before an exact-state rule is added. |
| P2 | Verify gem persistence across chapters | Enemy-to-enemy persistence is known; chapter-boundary persistence is not proven. | Log gem identity and position before the boss, after it, and on the next chapter's first READY. | At least two controlled boundaries preserve the same gem state. |
| P2 | Verify any remaining boss word-length immunities | Mama Roc and Medusa are modeled. Do not generalize their rule to every boss without native evidence. | For any new suspect, compare exact native selection validity for three-letter words with a four-plus-letter control, or identify the native creature rule directly. | Each additional boss has native evidence and a regression fixture before its candidates are filtered. |
| P2 | Build deterministic strategy simulations | The live solver is locally greedy and does not plan saved letters, gems, treasures, future enemies, or survival across a chapter. | Start with Book 1 deterministic replay and compare candidate objectives before changing the live default. | Simulations predict live outcomes and improve held-out-seed splits. |

## Full-run acceptance

- Complete a fresh-profile uninterrupted run through Codex.
- Record every chapter/book split and the full-run total.
- Confirm no deaths, manual recovery, unsafe tile-grid fallback clicks, or
  acknowledgement retries.
- Confirm PLAY, multi-page dialogue, level-ups, boss resets, treasures,
  stun/freeze/petrify, Sphinx, Ali Baba, and all book transitions.
- Compare every split with both TAS-best and human-WR data.

## Recently verified and closed

- Indexed candidates produce decisions roughly 130–185 ms after native READY.
- Completed words submit at the first native ownership edge with bounded Enter
  retries. The latest clean Chapters 1 and 2 had no input retries.
- Submission during valid-word presentation is recognized immediately, so
  powered attacks no longer wait through the former eight-second timeout.
- Current records: Chapter 1 **1:04.895**; Chapter 2 **1:08.535**. Chapter 2
  improved by **7.016 seconds** and beats the human segment by **6.165 seconds**.
- Power-Up uses the native effect/multiplier and is considered before healing.
- Purify no longer clicks the old overlay after the rack regains ownership;
  live petrification testing confirmed the following word remains intact.
- Genuine post-reset level-up and post-treasure conversation screens now clear
  stale reset suppression and replay blocked menu exits.
- Fresh-profile PLAY, filename timing, menu focus, structured logging, crash
  capture, and single-runner locking are implemented.
- Native weighted length, intrinsic letter tiers, and half-up damage rounding
  are modeled.
- Medusa's minimum-four-letter rule is now proven by native telemetry: six
  different three-letter paths reached exactly three selected tiles but all
  remained invalid and emitted no Attack-ready edge. Medusa now shares Mama
  Roc's candidate filter.

## Lower-priority strategy inventory

Future simulation work should cover bonus words, infected/blocked tiles,
character weaknesses, Hand of Hercules and metal words, Wooden Parrot, Tome of
the Ancients, Jeweled Key, Sphinx answers, title/save menus, and saved-letter or
gem planning.
