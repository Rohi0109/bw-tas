# Bookworm Adventures Deluxe TAS handoff

## Current objective

Build a full-game, unattended Bookworm Adventures Deluxe TAS targeting under 36
minutes from character selection through the end of Book 3. The current work is
on branch `feature/full-run-validation` in `/home/rnadgir/Bookworm-google`.

The original installed game is preserved. Automation rebuilds a disposable
modded copy under `runtime/deluxe-modded/`.

## Common commands

- `just game` launches the disposable modded Deluxe copy.
- `just menu-start` enters Adventure mode from the title screen.
- `just tas` attaches the continuous Deluxe runner.
- `just test` runs the Python unit tests.
- `./prepare-deluxe-tas.sh` rebuilds the modded `main.pak` after Lua-hook edits.

For reliable startup, launch the game, wait for the title screen, start `just
tas`, and then run `just menu-start`. Starting the runner after combat has
already emitted its sole READY snapshot can leave it waiting for another event.

## Implemented and live-tested this session

- Added Lua chapter-map, chapter-action, treasure-context, mini-game-prompt, and
  dialogue telemetry used by the runner.
- Added automatic chapter entry, dialogue advancement, deterministic treasure
  selection, Moxie skip confirmation, and recovery/retry behavior.
- Added the five fixed Sphinx answers from the shipped `mPuzzleWords` table:
  `SKY`, `WALL`, `FIST`, `TRUTH`, and `WATER`. The final board is installed
  incrementally, so an early READY can expose an incomplete `WAT...` board;
  wait for a later Lua board rather than attacking or scrambling.
- Mama Roc filters out three-letter words because they are immune.
- Ordinary fights heal before attacking when Lex has four hearts or fewer,
  including predicted killing blows so low health is not carried into the next
  encounter. Hydra and the Book 3 final gauntlet retain conservative full-heal
  behavior. Known petrify encounters use Purify.
- Boss finishing turns use the shortest lethal candidate to avoid useless
  overkill animation time.
- Added book-movie skip confirmation after a Chapter 10 boss stalls.
- Added pre-boss menu resets after the penultimate encounter and route-specific
  midchapter resets.
- Added an immediate Lua `AUTOMATION_ZERO_HEALTH` event. The runner uses it to
  exit to the main menu immediately after a chapter boss reaches zero HP, then
  re-enters Adventure mode. This was live-tested successfully on Eternal
  Wanderer, Frankenstein, and The Wolf-Man, and it advanced to the next chapter
  without replaying the defeated chapter.
- Added a simple chapter/book timer and tests, but a clean complete timed run has
  not yet been achieved.

## Latest treasure issue

During a Book 3 treasure room, automation selected only two treasures and left
Continue disabled. A subsequent recovery click produced Hand of Hercules, Robe
of the Unseen, and Wooden Parrot instead of the desired Arch of Xyzzy, Hand of
Hercules, and Wooden Parrot.

The Book 3 route is currently restored to slots `(0, 6, 10)` at the user's
request. Do not change this mapping based only on the last screenshot. The
larger bug is that `select_treasures()` blindly clicks every desired slot. If a
treasure is already selected, clicking it toggles it off. A robust fix should
instrument the treasure screen's current selected state (or otherwise reset it
deterministically) and click only the symmetric difference between current and
desired selections. Confirm actual slot identities from telemetry/live tests.

## Important remaining issues

- Add a stun-animation fast path: when Lua reports Lex is stunned, click one
  confirmed-selectable tile to skip/shorten the animation, then wait for fresh
  Lua board/status telemetry before selecting the actual combat word.
- Integrate chapter high-score timing with TAS telemetry. Start each split on a
  Lua-confirmed chapter gameplay-entry event and stop it only after a confirmed
  native main-menu exit following the chapter boss. Persist the best (lowest)
  time per chapter and overwrite a record only when a faster split completes.
- Post-boss re-entry retries can remain armed longer than necessary. They are
  disarmed on treasure, chapter, and board events, but live output still showed
  repeated `Retrying Adventure` messages before the treasure screen. Add a
  definitive main-menu/adventure-entry acknowledgement if those clicks cause
  trouble.
- Runner startup recovery can inherit a stale unresolved Moxie prompt and print
  `Recovering Lua-confirmed mini-game prompt`; improve event scoping if it
  becomes harmful.
- Complete a fresh-profile, uninterrupted full-game run and record chapter/book
  splits. Validate treasure choices, cutscene skips, deaths, and all three book
  transitions.
- Validate the Ali Baba chapter pre-boss exit after `Thief 9, 10 & 11`; the
  final boss is `Thief 12, 13 & 14 (Boss)`. Its defeat can be followed by a
  guaranteed level-up overlay, so reset when Lua acknowledges the accepted
  lethal attack, while the native battle menu is still available.
- Keep all five Sphinx rounds on their fixed puzzle answers without Scramble;
  on the last round, prefer `WATER`, allow a normal word only when it is a
  predicted one-shot, and otherwise wait through incomplete board telemetry.
- Schedule a solver-improvement session: build deterministic board/enemy
  simulations and compare richer candidate-search strategies before changing
  the live default.
- Power-up strategy remains a high priority: use power-ups after Power Down for
  enemies above an initially proposed 10-heart threshold; explore the best HP
  threshold and potion timing.
- Roadmap items discussed: bonus words, infected/blocked tiles, character-specific
  weaknesses, Hand of Hercules and metal words, Wooden Parrot, Tome of the
  Ancients, Jeweled Key, power-up potion behavior, Sphinx hardcoding, title/save
  menus, deterministic treasure selection, and recovery/timing telemetry.

## Repository hygiene

The worktree is intentionally dirty and contains user-owned/unrelated untracked
files, including `index.html`, the roll HTML files, `web/`, `speedrun/.vscode/`,
and `speedrun/general things exist to main menu after`. Preserve them. Do not
bulk-clean or reset the worktree.

At the end of this handoff, the expected test count is 70. Run `just test` and
`git diff --check` before committing. No commit or push was requested for this
last session.
