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
just prepare-deluxe
just deluxe
```

Enter a battle, leave the game open, then run this in another terminal:

```bash
./run-deluxe-speedrun-auto.sh
```

Or, in the second terminal:

```bash
just deluxe-auto
just deluxe-auto -- --strategy max-damage
just speedrun-auto -- --strategy max-damage  # Deluxe alias
```

The Deluxe runner now uses live enemy HP, offense, enabled treasures, physical
gem tiles, and the game's overkill thresholds. Its default strategy is:

- Before gems unlock: choose the fastest lethal word.
- After gems unlock: reach the best available overkill gem tier, then choose
  the fastest word within that tier.
- If no word is lethal: choose the best predicted damage per second.

Compare policies with `--strategy shortest-lethal` or
`--strategy max-damage`. Every choice prints its damage, overkill tier, and
alternatives. Completed attacks append timing samples to
`runtime/deluxe-modded/tas-timing.jsonl`.

If a board has no playable dictionary word, the runner clicks Scramble and
waits for a new sequence-tagged Lua snapshot before solving again. Scrambles
have their own safety limit (`--max-scrambles`, default 10), separate from the
attack limit.

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

#### Tile hazards and potion optimization plan

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
4. Emit power-up potion inventory and active `DamageMultiplierEffect` state.
   Deluxe's `AttackItem` applies a next-attack multiplier (described by the
   shipped game as x2); do not infer availability merely from `AllowItems`.
5. Add potion activation to the controller and measure its click/animation
   cost. Compare attack-now, potion-then-attack, and scramble policies while
   accounting for the potion as a finite resource.
6. Add health and purify potions separately. They affect survival/board state,
   not direct word damage, and need their own decision rules.

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
4. Automate chapter and book transitions while waiting on explicit Lua/menu
   state instead of fixed delays.
5. Automate title-screen and save/profile selection, with an explicit configured
   save target so the TAS never guesses which profile to modify or load.
6. Add recovery logic and timing telemetry for unexpected dialogs, loading
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
