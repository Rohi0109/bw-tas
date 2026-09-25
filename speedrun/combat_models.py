"""Immutable shared combat values. No I/O or solver dependencies."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DeluxeState:
    sequence: int
    board: str
    gems: tuple[str, ...]
    tile_powers: tuple[float, ...]
    book: int
    chapter: int
    stage: int
    enemy: str
    hp: float
    max_hp: float
    offense: float
    treasures: frozenset[str]
    overkill_thresholds: tuple[float, ...]
    selectable: tuple[bool, ...] = (True,) * 16
    player_hp: float = -1
    player_max_hp: float = -1
    player_stunned: bool = False
    player_frozen: bool = False
    player_petrified: bool = False
    health_potion_available: bool = False
    attack_potion_available: bool = False
    player_powered_up: bool = False
    player_damage_multiplier: float = 1.0
    player_has_damage_over_time: bool = False
    zero_damage: tuple[bool, ...] = (False,) * 16
    rng_calls: int = -1


@dataclass(frozen=True)
class Candidate:
    word: str
    path: tuple[int, ...]
    damage: float
    overkill: float
    tier: str | None
    lethal: bool
    predicted_time: float
    gem_count: int
    gem_types: tuple[str, ...] = ()
    animation_class: str = "unknown"


@dataclass(frozen=True)
class WordSpec:
    word: str
    letter_mask: int
    requirements: tuple[tuple[str, int], ...]
