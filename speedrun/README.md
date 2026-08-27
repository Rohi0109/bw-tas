## Bookworm speedrun notes

The solver now supports two board sources:

- Random board generation for local testing.
- Manual board input with `--board`, for example `ABCD/EFGH/IJKL/MNOP`.

Run it with:

```bash
python main.py --board "CART/DOGS/LINE/PUMB"
```

## Live game integration

To connect this to the real game, keep the pipeline narrow:

1. Acquire board state from the game window or process.
2. Convert that state into the 4x4 text format consumed by `parse_board`.
3. Feed the resulting `Board` into `solve_board`.
4. Send the chosen path back into your TAS/input layer.

For the first step, there are two practical options:

- Window capture plus template matching or OCR for each tile.
- Memory inspection if you can locate the board letters directly in the game process.

Window capture is usually easier to prototype. Memory inspection is usually faster and more stable once you know the offsets.

## Deluxe TAS prototype

The Deluxe build is instrumented in a disposable copy; the installed game and
its original `main.pak` are never edited.

```bash
./prepare-deluxe-tas.sh
./run-deluxe-tas.sh
```

The equivalent [just](https://just.systems/) recipes are:

```bash
just setup
just game
```

Enter a battle, leave the game open, then run this in another terminal:

```bash
./run-deluxe-speedrun-auto.sh
```

Or, in the second terminal:

```bash
just tas
just tas --strategy max-damage
```

The Deluxe runner now uses live enemy HP, offense, enabled treasures, physical
gem tiles, and the game's overkill thresholds. Its default `chapter-aware`
strategy is:

Per-letter treasure effects are read from the game's live tile-power result.
This includes Wooden Parrot's bonus for every selected `R` tile and Bow/Arch of
Xyzzy's bonuses for `X`, `Y`, and `Z`; the optimizer consumes those values once
and does not duplicate the bonus in Python. Hand of Hercules and Heph's Hammer
are applied separately because they modify the completed attack rather than an
individual tile.

- Book 1, Chapters 1–5: choose the fastest lethal word to avoid unnecessary
  long-word animation time.
- In other gem-locked states: choose the maximum-damage word.
- From Book 1, Chapter 6 onward when gems are enabled: reach the best available
  overkill gem tier, then choose
  the fastest word within that tier.
- If no word is lethal: choose the best predicted damage per second.

The switch uses live gem/overkill availability emitted by Lua, so modified
saves and chapters still select the correct policy. Override it with
`--strategy shortest-lethal`, `--strategy max-damage`, or
`--strategy overkill-tier`. Every choice prints its strategy, damage, tier, and
alternatives. Completed attacks append timing samples to
`runtime/deluxe-modded/tas-timing.jsonl`.

If a board has no playable dictionary word, the runner clicks Scramble and
waits for a new sequence-tagged Lua snapshot before solving again. Scrambles
have their own safety limit (`--max-scrambles`, default 10), separate from the
attack limit.

#### Power-Up Potion optimization plan (highest priority)

1. Emit the live power-up potion inventory and active
   `DamageMultiplierEffect` state. Deluxe's `AttackItem` applies a next-attack
   multiplier (described by the shipped game as x2); do not infer availability
   merely from `AllowItems`.
2. Add potion activation to the controller and wait for Lua-confirmed item
   activation and board readiness before selecting the word.
3. Compare attack-now against potion-then-attack using enemy HP, predicted word
   damage, and the potion's click/effect animation cost. Prefer potion use when
   it crosses a breakpoint that removes an attack or another long animation.
4. Treat potions as a finite route-wide resource. Use run telemetry to assign
   them to the encounters with the largest measured time savings instead of
   greedily spending one on the first damage increase.
5. Verify multiplier order and rounding with gems, offense, treasures, metal
   words, and enemy weaknesses before enabling those combinations by default.
6. Log inventory before/after, chosen word, predicted and observed damage, item
   animation time, and attacks saved so the route can be tuned from real runs.
7. Add health and purify potions separately. They affect survival or board
   state rather than direct damage and need their own decision rules.

#### Scramble optimization plan

1. **Implemented:** scramble only when the candidate set is empty.
2. Record candidate count, best damage, predicted attack time, and measured
   scramble-to-ready time in the timing JSONL.
3. Add an opt-in weak-board policy using measurable thresholds (for example,
   no lethal word plus best damage below a configured value), while retaining
   the no-word fallback as the safe default.
4. Compare attack-now versus scramble policies per enemy/HP state from actual
   run telemetry, then promote a policy to the TAS default only when it saves
   measured time.

#### Tile-hazard optimization plan

1. Extend each tile snapshot with its live class/attribute flags and individual
   `CanSelect` result. A zero `AUTOMATION_POWERS` value is not enough to
   distinguish an ordinary tile from an infected, locked, blocked, black, or
   otherwise non-scoring tile.
2. Reject paths containing individually unselectable/blocked tiles. Model
   infected-tile spread, expiration, purification, and any attack/score penalty
   separately from physical selection restrictions.
3. Calculate base word damage from only the scoring tiles, then verify
   predicted versus observed HP loss on controlled black/infected-tile attacks
   before enabling the model by default.

#### Bonus-word optimization plan

1. Emit the live bonus-word objective, completion state, and exact reward from
   Lua instead of trying to infer them from pixels.
2. Mark which candidate words satisfy the objective and include the reward in
   predicted damage/resource value.
3. Measure any extra celebration or reward animation time. Compare the fastest
   ordinary attack against the best qualifying bonus word rather than always
   preferring the bonus.
4. Track objectives that persist between enemies separately from objectives
   that expire, so the TAS can defer a bonus word when completing it later is
   faster.

#### Hand of Hercules and metal-word plan

1. **Provisionally implemented:** load the shipped metal-word set from
   `metals.luc` and identify qualifying candidates directly, rather than
   guessing from spelling.
2. **Provisionally implemented:** model Hand of Hercules as a x1.5 multiplier
   for metal words followed by its flat +1 damage bonus. Keep Heph's Hammer's
   separate flat bonus mutually exclusive with Hand.
3. Capture controlled attacks with Hand using both metal and non-metal words,
   then compare predicted damage against observed enemy HP loss to verify the
   multiplier, flat-bonus order, offense scaling, tile bonuses, and quarter
   rounding.
4. Measure Hand/metal-specific effect animation time and include it in word
   ranking. A shorter non-metal lethal word may be faster than a higher-damage
   metal word once its effect animation is counted.
5. Add regression fixtures from verified live samples and remove the
   "provisional" status only when every damage-order case matches the game.

#### Tome of the Ancients and color-word plan

1. Extract the shipped color-word set from the Deluxe game data instead of
   maintaining a guessed list. Include uncommon color names only when the game
   itself recognizes them for the treasure bonus.
2. Detect Tome of the Ancients in the live enabled-treasure snapshot and mark
   every playable qualifying candidate. Model its advertised 100% bonus damage
   using the game's actual rounding and modifier order.
3. Measure how frequently useful color words occur on real TAS boards,
   especially longer common-letter words that can overcome the category's low
   candidate count with doubled damage.
4. Measure the Tome activation animation and compare total turn time against
   the fastest ordinary lethal word, Wooden Parrot candidates, and Hand of
   Hercules metal words. Do not equip or prefer Tome based on damage alone.
5. Evaluate Tome per chapter and enemy HP breakpoint. It may be worthwhile only
   for specific fights where a reproducible color word saves an entire attack;
   otherwise its treasure slot and low activation rate likely make it slower.
6. Add verified live damage/timing fixtures before enabling Tome in the default
   chapter-aware loadout map.

#### Jeweled Key and gem-generation plan

1. Model Jeweled Key using the shipped weighted-word-length rules: a 3-weight
   word has a 5% Amethyst chance, a 4-weight word has a 25% Amethyst chance,
   and a 5-weight word produces either an Amethyst (75%) or Emerald (25%). It
   does not improve the normal gem rewards for longer words or overkills.
2. Add a Book 2, Chapter 4 loadout experiment for the fixed Sphinx answers:
   `SKY` (weight 3), `WALL` and `FIST` (weight 4), then `TRUTH` and `WATER`
   (weight 5). The last two should guarantee gems, for 2.55 expected generated
   gems across all five riddles.
3. Extend Lua telemetry to distinguish newly spawned gems from gems already on
   the board and gems consumed by an attack. Record the spawning word, gem
   type, board position, enabled treasure, and time until the next READY event.
4. Compare the Sphinx chapter and following fights with and without Jeweled
   Key. Include treasure-selection time and later gem activation animations;
   generated gems are valuable only when they reduce total run time.
5. If verified, equip Jeweled Key specifically for the Sphinx chapter and drop
   it afterward. Normal optimizer-selected long words receive no Key benefit,
   so it should not occupy a default offensive slot outside this breakpoint.
6. Repeat the experiment for Endless Gem Pouch after it replaces Jeweled Key,
   using its separate 3/4/5-weight probabilities rather than treating it as an
   identical rename.

#### Enemy-specific weakness and immunity plan

1. Extract each creature's shipped weakness, resistance, immunity, defense,
   and phase-specific rules from its Deluxe Lua/data files. Keep display-name
   aliases separate from combat behavior so renamed enemies still resolve to
   the correct model.
2. Extend live Lua snapshots with the active enemy effects and modifiers rather
   than relying only on a static roster. Boss phases, temporary armor, power
   states, and conditional immunities must update immediately.
3. Model direct word constraints first: minimum/maximum word length, immunity to
   short words, letter/category weaknesses, and damage multipliers or reducers.
   Reject a candidate that the current enemy will ignore even if its unmodified
   damage would otherwise be lethal.
4. Model gem side effects separately from gem damage. Poison, burn, freeze,
   power down, stun, and healing may be resisted or immune while the gem's
   direct damage multiplier still applies.
5. Include enemy-specific reaction and effect-animation time in candidate
   ranking. Prefer a weaker-looking word when it avoids a slow weakness,
   resistance, transformation, or multi-phase animation and wins sooner.
6. Add fixtures for every exceptional enemy and boss phase using observed HP
   deltas and logs. Unknown combat modifiers should produce a clear warning or
   safe stop instead of silently using generic damage.
7. Feed verified rules into the chapter-aware treasure map. Equip category or
   status treasures only where the enemy roster makes their benefit reliable.

#### Main-menu exit and Adventure re-entry plan

1. **High priority:** use the in-game Main Menu button after progress has been
   committed, then select Adventure mode to re-enter at the next actionable
   state. This route can skip post-boss dialogue, long walks between battles,
   and other slow non-combat transitions; it is not limited to boss fights.
2. Identify the earliest explicit Lua/save event that makes a menu exit safe.
   Verify enemy, chapter, reward, experience, treasure, and profile progress are
   durable before clicking Main Menu. Never infer safety from zero HP or a fixed
   delay alone.
3. Automate the full deterministic sequence: open the battle menu, click Main
   Menu, wait for the title screen, choose Adventure, select the configured
   profile if required, and wait for a known re-entry state before resuming TAS
   input.
4. Build a route map of every transition where menu re-entry is faster,
   including post-boss dialogue and long inter-battle walks. Some checkpoints
   may reload the previous fight, omit an uncommitted reward, add extra dialogue,
   or take longer than remaining in-game, so do not apply the reset globally.
5. Measure both routes from the same committed state through the next actionable
   combat READY event. Include menu input, loading, Adventure selection,
   re-entry dialogue, and any treasure/loadout screen in the comparison.
6. Add explicit Lua states for progress committed, safe-to-exit, pause/battle
   menu, main menu, Adventure selection, profile selection, loading, and re-entry
   complete. Generic dialogue probes must remain disabled on all menu screens.
7. Add recovery and save-integrity checks. If re-entry does not produce the
   expected chapter, stage, rewards, or unlocked treasures, stop safely instead
   of continuing on a divergent route.
8. Store measured normal-versus-reset timings and let the TAS choose the faster
   verified route for the current checkpoint and machine/loading profile.

#### End-to-end dialogue and menu automation plan

1. **In progress:** Lua-tagged dialogue advancement. Level-up overlays and
   active story conversation panels emit Lua-confirmed events and are clicked
   by default (`--no-auto-dialog` disables it). Multi-page panels use an active
   heartbeat because the native panel API exposes no page index; clicks stop as
   soon as Lua reports the panel inactive. Add additional tutorial types without
   falling back to screen-only timeout clicks.
   Native conversation widgets suspend both TileEngine and BattleEngine Lua
   updates; when the runner is started in battle with an empty log, it probes
   the safe conversation area after `--dialog-stall-delay` until Lua telemetry
   resumes. Do not start the combat runner from an unidentified menu screen.
2. Automate victory and continue screens, including post-battle rewards and
   chapter-complete transitions.
3. Implement deterministic treasure selection from a chapter-aware loadout
   map, accounting for unlock order and the number of available slots.
4. Add deterministic Sphinx-level automation by mapping each known riddle or
   prompt to its hardcoded answer. Identify the prompt from Lua state when
   possible, validate that the expected answer is playable, and stop safely or
   fall back to the normal solver when an unknown prompt appears.
5. Automate chapter and book transitions while waiting on explicit Lua/menu
   state instead of fixed delays.
6. Automate title-screen and save/profile selection, with an explicit configured
   save target so the TAS never guesses which profile to modify or load.
7. Add recovery logic and timing telemetry for unexpected dialogs, loading
   screens, missed inputs, and menu-state mismatches. Recovery must stop safely
   when the current screen cannot be identified.

Preparation may be rerun safely. It always rebuilds from
`runtime/deluxe-modded/.tas-original-main.pak` and replaces only
`scripts/TileEngine.luc` in the staged PAK.

### Play one live turn

This copied working tree includes a local bridge to the Wine launcher:

```bash
../run-speedrun-turn.sh --board "CART/DOGS/LINE/PUMB"
```

It prints the highest-damage word, locates the `Bookworm Adventures` Wine
client, clicks the corresponding tile occurrences, and clicks Attack. Add
`--dry-run` to solve without sending input. The next integration step is to
supply `--board` from screen capture.
