# Recovered word-damage stages

`native_damage_model.py` separates intrinsic weighted value, tier/base damage,
base-scaled gem bonuses, bonus quantization and offense. It operates before
enemy damage resolution, rather than assuming an observed net HP delta is
direct word damage. The live solver is unchanged.

Source: preserved Deluxe `runtime/deluxe-modded/.tas-original-main.pak`:

- `scripts/TileEngine.luc`, prototypes 5 and 7: positive modified values are
  summed, rounded and capped at tier 16; each ApplyBonus receives base damage;
  bonuses are summed then quarter-ceiled, and offense applies to base only.
- `scripts/BattleEngine.luc`, top-level instructions 21–29: gem percentages
  amethyst .15, sapphire .25, emerald .2, garnet .3, ruby .35, crystal .5, diamond 1.
- All seven standard `scripts/tiles/*Tile.luc` gem classes, prototype 6:
  identical instruction sequences and constant tables implement bonus percentage
  times base word damage times enemy gem multiplier.
- `scripts/common.luc`, DecimalCeil prototype 20: quarter-ceiling helper.

The five nonlethal native fixtures validate plain tier/offense/full-damage and
quarter-HP stages. Gem tests check recovered formulas and arithmetic boundaries;
they do **not** constitute independent native gem outcome validation. Capture
base/full values for identical gem types at multiple tiers before promoting
gem handling to native-verified combat support.

Still excluded: nonstandard tile attributes, gem ApplyEffects, status/treasure
ordering, enemy damage buffers, defenses, regeneration, DOT, attack selection
and round scheduling. Callers must supply modified intrinsic tile values and
explicit enemy gem modifiers. A quarter-floor primitive alone is not the enemy
damage-resolution pipeline.
