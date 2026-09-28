"""Native enemy AI: urgency, attack selection, and counter update.

Evidence basis: handoff-documented bytecode locations in the pinned Deluxe build
(7fa527a5...). Prototypes are zero-based.

- CreatureBaseClass.luc proto 28: attack selection
- attacks/AttackBaseClass.luc protos 5/6: GetUrgency / CanAttack
- common.luc proto 31: UrgencyChooser

What is NOT native-verified:
- Tie-breaking inside the weighted band (QRand vs engine RNG vs ordering).
- The exact role of mAlreadyPerformed: treated here as an ineligibility flag.
- Per-enemy CanAttack Lua overrides (boss phases, special enemies).
- No native encounter fixtures confirm these rules end-to-end.
"""
from __future__ import annotations

import math
from enum import IntEnum
from typing import Callable, Optional

# Lua hook field names → canonical AI field names.
_LUA_FIELD_MAP: dict[str, str] = {
    'mMin': 'min',
    'mMax': 'max',
    'mDamage': 'damage',
    'mAlreadyPerformed': 'already_performed',
    # mState intentionally absent: numeric→string mapping unconfirmed.
    # Preserved as 'native_state_raw' until native capture confirms the mapping.
}

_CANONICAL_KEYS = frozenset({
    'min', 'max', 'damage', 'already_performed', 'state',
    'name', 'rate_counter', 'native_state_raw',
})


def normalise_attack(raw: dict) -> dict:
    """Translate a Lua hook attack dict to the canonical AI field names.

    Accepts either m-prefixed (hook) format or canonical format, but not
    mixed. mState is preserved as native_state_raw; its integer→string
    mapping is unconfirmed and kept for future native capture evidence.

    Raises ValueError for unknown keys or mixed representations.
    """
    if not isinstance(raw, dict):
        raise ValueError(f'attack entry must be a dict, got {type(raw).__name__!r}')
    # Lua hook keys are camelCase: mMin, mMax, mState, etc. (lowercase 'm' + uppercase next char).
    m_keys = {k for k in raw if k.startswith('m') and len(k) > 1 and k[1].isupper()}
    canonical_in_input = set(raw) - m_keys
    if m_keys and (canonical_in_input & (_CANONICAL_KEYS - {'native_state_raw'})):
        raise ValueError(
            f'attack mixes m-prefixed and canonical keys: '
            f'm-prefixed={m_keys!r}, canonical={canonical_in_input!r}')
    if not m_keys:
        unknown = set(raw) - _CANONICAL_KEYS
        if unknown:
            raise ValueError(f'attack has unknown canonical keys: {unknown!r}')
        return dict(raw)
    result: dict = {}
    for k, v in raw.items():
        if k == 'mState':
            result['native_state_raw'] = v
        elif k in _LUA_FIELD_MAP:
            result[_LUA_FIELD_MAP[k]] = v
        else:
            raise ValueError(f'unknown m-prefixed attack field: {k!r}')
    return result


class UrgencyLevel(IntEnum):
    """Three-level classification derived from the 0-100 urgency_weight scale.

    LOW:    weight == 0 (not yet eligible; counter < min).
    MEDIUM: 0 < weight < 100 (eligible, not overdue).
    HIGH:   weight >= 100 (overdue; counter >= max and max > 0, or max == min).
    """
    LOW = 0
    MEDIUM = 1
    HIGH = 2


def urgency_weight(attack: dict, counter: int) -> int:
    """Return urgency as a 0-100 integer.

    Mirrors campaign_simulator.urgency() exactly, which recovers the formula in
    AttackBaseClass GetUrgency (protos 5/6).

    0: not eligible (counter < min).
    100: overdue (counter >= max > 0, or max == min, or max < min as no-bound sentinel).
    1..99: eligible, not yet overdue.

    max == 0 with min > 0 is treated as max < min (no-upper-bound sentinel → weight=1).
    """
    minimum = attack['min']
    maximum = attack['max']
    if counter < minimum:
        return 0
    if maximum == minimum:
        return 100
    if maximum < minimum:
        return 1
    return min(100, max(1, math.floor(100 * (counter - minimum + 1) / (maximum - minimum + 1))))


def get_urgency(attack: dict, counter: int) -> UrgencyLevel:
    """Classify urgency using the 0-100 scale; for documentation and tests."""
    w = urgency_weight(attack, counter)
    if w == 0:
        return UrgencyLevel.LOW
    if w >= 100:
        return UrgencyLevel.HIGH
    return UrgencyLevel.MEDIUM


def _is_eligible(attack: dict, counter: int) -> bool:
    if attack.get('state') == 'inactive':
        return False
    if attack.get('already_performed', False):
        return False
    return urgency_weight(attack, counter) > 0


def choose_attack(
    attacks: list[dict],
    counters: list[int],
    draw: Optional[Callable[[str], int]] = None,
) -> Optional[int]:
    """Select the attack index the enemy will use this turn.

    Derived from CreatureBaseClass.luc proto 28 and common.luc proto 31 (UrgencyChooser),
    preserving the weighted urgency and RNG consumption behaviour from campaign_simulator.

    Selection order:
    1. Compute 0-100 urgency weight for each eligible attack.
    2. Due attacks (weight >= 100): if exactly one, return it without consuming a draw.
       If multiple, consume draw('ai-due') and index into the due list.
    3. No due attacks: consume draw('ai-weighted') for weighted random selection over
       the 0-99 weight distribution. If total weight is zero (all ineligible), return None.

    Note: a single non-due eligible attack (weight 1-99) still consumes draw('ai-weighted').
    Only a sole DUE attack (weight >= 100) skips the draw (handled in step 2 above).

    Args:
        attacks:  Attack definition dicts (min, max, state, already_performed, damage, ...).
        counters: Per-attack use counters, same length as attacks.
        draw:     Callable(label: str) -> int.  Must be provided when a randomised choice
                  is actually needed (multiple due, or weighted selection including a single
                  non-due eligible attack); may be None only when a sole due attack or no
                  eligible attack obviates randomness.

    Returns:
        Index of the chosen attack, or None if no attack is eligible.

    Approximations (not native-verified):
        - draw() is expected to return a native engine RNG value; the exact label/consumer
          string is an approximation.
        - mAlreadyPerformed semantics and per-enemy CanAttack overrides are unconfirmed.
    """
    if len(attacks) != len(counters):
        raise ValueError('attacks and counters must have the same length')

    eligible = [
        (i, urgency_weight(attacks[i], counters[i]))
        for i in range(len(attacks))
        if _is_eligible(attacks[i], counters[i])
    ]
    if not eligible:
        return None

    due = [i for i, w in eligible if w >= 100]
    if len(due) == 1:
        return due[0]
    if due:
        if draw is None:
            raise ValueError('draw required to break tie among multiple due attacks')
        return due[draw('ai-due') % len(due)]

    total = sum(w for _, w in eligible)
    if not total:
        return None
    if draw is None:
        raise ValueError('draw required for weighted attack selection')
    value = draw('ai-weighted') % total
    for i, weight in eligible:
        if value < weight:
            return i
        value -= weight
    raise AssertionError('Unreachable: weighted selection fell through')


def tick_counters(counters: list[int], active_attack_index: Optional[int]) -> list[int]:
    """Increment all counters; reset the active attack's counter to 0.

    Mirrors campaign_simulator.py inline counter policy (proto 28).
    Returns a new list; input is not mutated.

    Approximation: whether counters increment on a skipped enemy turn is a scenario
    policy inherited from campaign_simulator.py, not independently native-verified.
    """
    result = [c + 1 for c in counters]
    if active_attack_index is not None:
        result[active_attack_index] = 0
    return result
