"""Recovered pre-enemy word-damage stages; no enemy turns or effect execution.

Inputs are the selected tiles' already-modified intrinsic values and gem types.
Treasure/status ModifyValue effects must be resolved by the caller. This module
does not reinterpret telemetry's letter-scaled tile_powers as gem bonuses.
"""

from dataclasses import dataclass
import math


DAMAGE_TABLE = (0., .25, .25, .5, .75, 1., 1.5, 2., 2.75,
                3.5, 4.5, 5.5, 6.75, 8., 9.5, 11., 13.)
GEM_BONUS_PCT = {'none': 0., 'amethyst': .15, 'sapphire': .25,
                 'emerald': .2, 'garnet': .3, 'ruby': .35,
                 'crystal': .5, 'diamond': 1.}


@dataclass(frozen=True)
class DamageBreakdown:
    weighted_value: float
    tier: int
    base: float
    raw_bonus: float
    quantized_bonus: float
    offense_bonus: float
    full: float


def word_damage(values, gems, *, offense=0., enemy_gem_multipliers=None):
    """Port GetWordValue/GetFullWordValue for selected standard gem tiles.

    Does not resolve additional tile attributes, Power-Up, gem ApplyEffects,
    enemy damage modifiers, HP clipping, or regeneration. Explicit multiplier
    values are required for an enemy with gem resistance/vulnerability.
    """
    values, gems = tuple(values), tuple(gems)
    if not 1 <= len(values) <= 16 or len(gems) != len(values):
        raise ValueError('Supply one value and gem per selected tile (1–16)')
    if any(g not in GEM_BONUS_PCT for g in gems):
        raise ValueError('Unknown gem')
    if not math.isfinite(offense) or any(not math.isfinite(v) for v in values):
        raise ValueError('Nonfinite damage inputs')
    multipliers = {} if enemy_gem_multipliers is None else dict(enemy_gem_multipliers)
    if (any(g not in GEM_BONUS_PCT for g in multipliers)
            or any(not math.isfinite(v) or v < 0 for v in multipliers.values())):
        raise ValueError('Invalid gem multipliers')
    # Native ignores non-positive ModifyValue contributions before tier lookup.
    weighted = sum(v for v in values if v > 0)
    tier = min(16, math.floor(weighted+.5))
    base = DAMAGE_TABLE[tier]
    raw_bonus = sum(GEM_BONUS_PCT[g] * base * multipliers.get(g, 1.) for g in gems)
    bonus = math.ceil(raw_bonus/.25)*.25 if raw_bonus > 0 else raw_bonus
    offense_bonus = base*offense
    full = max(0., base+bonus+offense_bonus)
    return DamageBreakdown(weighted, tier, base, raw_bonus, bonus, offense_bonus, full)


def quarter_hp_loss(resolved_damage):
    """Final quarter-floor primitive, after all external damage modifications.

    This is not a full CreatureBaseClass damage-buffer/effect implementation.
    """
    if not math.isfinite(resolved_damage) or resolved_damage < 0:
        raise ValueError('Expected finite nonnegative resolved damage')
    return math.floor(resolved_damage*4)/4
