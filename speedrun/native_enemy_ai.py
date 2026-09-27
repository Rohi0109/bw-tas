"""Native enemy AI: urgency, attack selection, and counter update.

Evidence basis: handoff-documented bytecode locations in the pinned Deluxe build
(7fa527a5...). Prototypes are zero-based.

- CreatureBaseClass.luc proto 28: attack selection (choose_attack semantics)
- attacks/AttackBaseClass.luc protos 5/6: GetUrgency / CanAttack base implementations
- common.luc proto 31: UrgencyChooser

What is NOT native-verified:
- Tie-breaking order within the same urgency level (index-order used here is an
  approximation; native may use QRand or a different ordering).
- The exact role of mAlreadyPerformed: treated here as an ineligibility flag, but
  native semantics have not been independently confirmed via bytecode.
- Per-enemy CanAttack Lua overrides (boss phases, special enemies).
- QRand streams used for chance-based attacks.
- No native encounter fixtures confirm these rules end-to-end.

None of these functions claim native-game parity. They replace the inline
urgency/choose_attack approximation in campaign_simulator.py with a named,
testable, documented module. Import them there once native fixtures confirm the
semantics.
"""
from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from native_rng import NativeRng


class UrgencyLevel(IntEnum):
    """Three-level urgency matching the documented Lua GetUrgency pattern.

    CreatureBaseClass.luc proto 28 selects attacks by urgency; HIGH (due)
    attacks take priority. The 0-100 scale in AttackBaseClass (protos 5/6) maps
    onto three tiers for selection purposes: below-min is not eligible, at-min
    is MEDIUM, and at-or-past-max is HIGH.

    Approximation: the native implementation may use the full 0-100 scale for
    weighted random selection rather than collapsing to three levels.
    """
    LOW = 1
    MEDIUM = 2
    HIGH = 3


def get_urgency(attack: dict, counter: int) -> UrgencyLevel:
    """Return the urgency level of an attack given its current use counter.

    Derived from AttackBaseClass GetUrgency (proto 5/6) and the thresholds
    used in CreatureBaseClass selection (proto 28).

    Rules (approximated from handoff evidence; not independently bytecode-verified):
    - counter >= attack['max'] and max > 0 → HIGH (attack is overdue)
    - counter >= attack['min']             → MEDIUM (attack is eligible)
    - counter <  attack['min']             → LOW (not yet eligible)

    Native caveat: the full urgency formula in AttackBaseClass uses a 0-100
    percentage scale. The three-level enum here captures the selection-relevant
    thresholds but loses the weighted probability within the MEDIUM band.
    """
    minimum = attack['min']
    maximum = attack['max']
    if maximum > 0 and counter >= maximum:
        return UrgencyLevel.HIGH
    if counter >= minimum:
        return UrgencyLevel.MEDIUM
    return UrgencyLevel.LOW


def _is_eligible(attack: dict, counter: int) -> bool:
    """An attack is eligible for selection if it meets minimum counter threshold,
    is not marked inactive, and has not already been performed this round.

    mAlreadyPerformed semantics: treated as an ineligibility flag (attack cannot
    be re-selected once performed in the current round). This interpretation is
    an approximation; the native CanAttack override per enemy has not been
    independently verified.
    """
    if attack.get('state') == 'inactive':
        return False
    if attack.get('already_performed', False):
        return False
    return counter >= attack['min']


def choose_attack(
    attacks: list[dict],
    rng: 'NativeRng | None',
    counters: list[int],
) -> int | None:
    """Select the attack index the enemy will use this turn.

    Derived from CreatureBaseClass.luc proto 28 (attack selection) and
    common.luc proto 31 (UrgencyChooser), as documented in the handoff.

    Selection rules (approximated; no native encounter fixtures yet):
    1. Filter to eligible attacks (see _is_eligible).
    2. Among eligible attacks, find those with the highest urgency level.
    3. If exactly one HIGH-urgency attack: select it without consuming an RNG draw
       (the native UrgencyChooser skips the draw for a sole due attack).
    4. If multiple attacks share the highest urgency: break ties by lowest index.
       Approximation: native may use QRand here; index-order is a stand-in.
       The `rng` parameter is accepted but NOT consumed here; callers that recover
       native tie-breaking behaviour should extend this function.
    5. If no eligible attacks: return None (enemy waits).

    Args:
        attacks:  List of attack definition dicts (keys: name, min, max, damage,
                  state, already_performed, rate_counter).
        rng:      Native RNG instance. Accepted for interface compatibility but
                  not consumed by the current approximation. Pass None if unknown.
        counters: Per-attack use counters, same length as attacks.

    Returns:
        Index into attacks of the chosen attack, or None.
    """
    if len(attacks) != len(counters):
        raise ValueError('attacks and counters must have the same length')

    eligible = [
        (i, get_urgency(attacks[i], counters[i]))
        for i in range(len(attacks))
        if _is_eligible(attacks[i], counters[i])
    ]
    if not eligible:
        return None

    best_level = max(level for _, level in eligible)
    candidates = [i for i, level in eligible if level == best_level]

    # Tie-break: lowest index wins (approximation; native may use QRand).
    return candidates[0]


def tick_counters(counters: list[int], active_attack_index: int | None) -> list[int]:
    """Update per-attack use counters after a turn.

    Derived from CreatureBaseClass.luc proto 28 counter management as described
    in the handoff (campaign_simulator.py implements the same policy inline).

    Rules:
    - All counters are incremented by 1 each turn (including skipped enemy turns).
    - The counter for the attack that was just used resets to 0 after the
      increment, so it starts the next round at 0, not 1.
    - If active_attack_index is None (no attack selected), all counters increment.

    Returns a new list; the input is not mutated.

    Approximation: whether counters increment on a skipped enemy turn is a
    scenario policy inherited from campaign_simulator.py, not independently
    native-verified.
    """
    result = [c + 1 for c in counters]
    if active_attack_index is not None:
        result[active_attack_index] = 0
    return result
