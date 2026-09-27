# Declarative campaign simulator

```sh
python3 speedrun/campaign_simulator.py speedrun/examples/campaign.json \
  --output /tmp/campaign.json
```

The included synthetic two-encounter campaign completes in three turns. It uses
no game process, X11, installed assets, model calls, or supplied refill stream.
`--max-turns 1` saves an intermediate report; pass that report with `--resume`
to continue. Checkpoints carry the definition, rack, both HP values, effect
durations, encounter index, XP, attack counters, RNG words/cursor and draw count.
`step(checkpoint, word)` supports independent action branches; omit the word to
select maximum immediate base damage. That strategy does not optimize effects.

## Implemented behavior and provenance

| Area | Implementation | Native confidence |
| --- | --- | --- |
| Enemy decisions | Eligible attacks, increasing urgency, due-attack priority, weighted random choice, selected counter reset | Formula recovered from normal turn-based `AttackBaseClass` prototypes 5/6, `common` prototype 31, and `CreatureBaseClass` prototype 28; no independent native outcome oracle yet |
| Effects | Poison, regeneration, stun/freeze skips, outgoing power and incoming shield multipliers, explicit expiry | Scenario-defined simplified mechanics; not native effect-class emulation |
| Progression | Ordered encounter list with book/chapter identity, XP/heal rewards, next-enemy setup, completion | Explicit scenario policy; no native boss phases, saves, loot selection, level-up, menus or book unlock rules |
| RNG scheduling | One checkpointed engine stream for letter selection, AI and explicit phase draws; every draw has consumer/index/value | Generator verified independently; the full native call schedule is not recovered |

Source inspection used the preserved installed Deluxe `.tas-original-main.pak`,
not the archived web assets. The native scripts include effect queues, QRand
chance logic, animation callbacks and special-case state that this model does
not execute. All reports explicitly carry `native_parity: false`.

SHA-256 of decoded members used for the urgency inspection:

```text
attacks/AttackBaseClass.luc cbe1731f1f9c20ce1993483bbc36bb5a900ae046390ab075a53f51f6d183b5fa
common.luc d2e3ac178d990cf8eb63caebf31847453579795f81c2cfd00aa73cd615b93653
creatures/CreatureBaseClass.luc f1389bbfff75cc292d24669ff1a10c8bf462e140230708d221a449b5e8900594
```

## Exact scenario phase order

1. Consume configured `before-player` draws. Tick player poison/regeneration.
2. Death cancels actions. Stun/freeze skips the word; otherwise select/validate
   a legal word and resolve damage with power/shield multipliers.
3. Decrement every player effect duration. Independent effect instances stack;
   poison/regen tick in list order, multipliers multiply, skip effects combine.
4. If a word was submitted, consume `before-refill` draws and refill in
   column-major order, including after lethal words. No gems are generated.
5. A defeated enemy grants configured rewards and consumes `encounter` draws,
   then enters the next encounter or completes the campaign. Retaliation is canceled.
6. Otherwise consume `before-enemy` draws and tick enemy poison/regeneration.
   Lethal poison advances the encounter without retaliation.
7. Increment all attack counters, even on skipped enemy turns. If not skipped,
   select an eligible attack, reset its counter, resolve damage, and append
   its status effects to the surviving player.
8. Decrement enemy effect durations, consume `after-enemy` draws, check player death.

These phases define the experiment, not a claim about native ordering. Duration
one lasts through the affected owner's next turn, not necessarily a full round.
In particular, a player's shield can expire before the following enemy turn.
No automatic effect merging, resistance rolls or purifying is implied.

## Input and limits

Use the example JSON as the schema. `initial` reuses the plain encounter input;
its `enemy_hp`/`enemy_attack` fields are validated but superseded by `encounters`.
Each attack has `min` and `max` urgency thresholds, damage and effects. A maximum
less than minimum gives constant urgency one once eligible. A sole due attack
consumes no choice draw; multiple due attacks use one uniform draw. Otherwise
positive urgencies use one weighted draw. No eligible attack produces a wait.

`rng_schedule` requires nonnegative draw counts for all five named phases.
These are configurable interleaved consumers, not discovered cosmetic draw
counts. All effect inputs require `kind`, positive integer `turns` and nonnegative
`value`. Unknown mechanics are rejected. Fresh output paths prevent overwrites.
Malformed checkpoint state is rejected before execution.

Stop conditions distinguish completion, player defeat, no playable word and
the turn limit. The campaign has no automatic scramble or word-dictionary import.
The example enemies are explicitly fictional training encounters. Do not label
this campaign a native TAS route or use its turn counts as measured speedups.

## Remaining native implementation

- Execute/port actual enemy-specific CanAttack overrides, effect queues and
  QRand streams; independently verify urgency choices and counter update timing.
- Recover status merge/resistance/use-dependent expiry and gem ApplyEffects.
- Import a build-pinned roster plus native HP, attack definitions, rewards,
  boss phase rules and checkpoint/save boundaries.
- Capture all shared engine RNG consumers with phase/order identity and replay
  their state, including cosmetic updates and conditional animation callbacks.
- Validate ordered native traces across held-out encounters before claiming parity.

Tests exercise branching/serialization, priority and RNG consumption, poison
death, skipped turns, modifiers, rewards and chapter transitions. These establish
the declared model's behavior, not full-game native fidelity.
