"""Complete encounter state schema for native-validated plain encounters.

Captures the full state required for P2 differential replay: board, both
combatants, RNG stream position, and eligibility classification.  Fields
that cannot be fully captured (gems, effects, QRand) are accepted but mark
the state UNSUPPORTED, preventing it from being used as a differential fixture.
"""
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from native_enemy_ai import normalise_attack

ENCOUNTER_STATE_VERSION = 1

_BOARD_RE = re.compile(r'[A-Z]{4}(?:/[A-Z]{4}){3}')
_HASH_RE = re.compile(r'[0-9a-f]{64}')


class EncounterEligibility(Enum):
    ELIGIBLE = 'eligible'
    UNSUPPORTED = 'unsupported'


@dataclass
class EncounterState:
    """Complete state for one native encounter instance.

    Build and session fields establish provenance.  Fields that cannot be
    fully captured (qrand_state, non-empty effects, non-plain gems) populate
    unsupported_fields automatically and yield EncounterEligibility.UNSUPPORTED.
    """
    # Schema version — checked on deserialise
    schema_version: int

    # Build and session identity
    build: dict               # {BookwormAdventures.exe: sha256, main.pak: sha256}
    session_id: str           # opaque string from capture session
    encounter_instance: int   # monotonic per-session counter (>= 0)

    # Board — 4×4 uppercase, rows joined by '/'
    board: str
    # Gem type per tile (16 values; 'none' for plain)
    gems: tuple              # UNSUPPORTED if any non-'none'
    # Tile power (16 floats; 0.0 for plain)
    tile_powers: tuple       # from solver; non-zero → not yet a native claim

    # Player
    player_hp: float
    player_max_hp: float
    player_offense: float
    player_damage_buffer: float
    player_effects: list     # UNSUPPORTED if non-empty (no native queue state)

    # Enemy
    enemy_name: str
    enemy_hp: float
    enemy_max_hp: float
    enemy_offense: float
    enemy_damage_buffer: float
    enemy_effects: list      # UNSUPPORTED if non-empty
    enemy_attacks: list      # list of attack dicts from Lua hook
    enemy_counters: list     # per-attack use counters (ints, parallel to enemy_attacks)

    # RNG streams
    engine_rng: dict         # {words: list[int] (624), cursor: int}
    engine_rng_draw_index: int  # draw index at encounter start (from RNG capture)
    qrand_state: Optional[object]  # must be None; non-None → UNSUPPORTED

    # Eligibility flags (populated by build_encounter_state)
    unsupported_fields: list


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_finite_nonneg(value, name):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f'{name} must be a number')
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be finite and non-negative')


def _require_int_nonneg(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f'{name} must be a non-negative integer')


def _validate_engine_rng(rng, name='engine_rng'):
    if not isinstance(rng, dict):
        raise ValueError(f'{name} must be a dict')
    words = rng.get('words')
    cursor = rng.get('cursor')
    if words is None or cursor is None:
        raise ValueError(f'{name} requires words and cursor')
    if len(words) != 624:
        raise ValueError(f'{name}.words must have exactly 624 elements')
    if any(not isinstance(w, int) or isinstance(w, bool) or not (0 <= w <= 0xFFFFFFFF)
           for w in words):
        raise ValueError(f'{name}.words must be unsigned 32-bit integers')
    if not isinstance(cursor, int) or isinstance(cursor, bool) or not (0 <= cursor <= 624):
        raise ValueError(f'{name}.cursor must be 0..624')


def _validate_build(build):
    if not isinstance(build, dict):
        raise ValueError('build must be a dict')
    for key in ('BookwormAdventures.exe', 'main.pak'):
        val = build.get(key)
        if not isinstance(val, str) or not _HASH_RE.fullmatch(val):
            raise ValueError(f'build[{key!r}] must be a 64-hex-char SHA-256')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_encounter_state(data: dict) -> 'EncounterState':
    """Construct an EncounterState from a raw data dict.

    Raises ValueError for missing or malformed required fields.
    Populates unsupported_fields for any field that prevents ELIGIBLE status.
    """
    missing = []
    for key in ('build', 'session_id', 'encounter_instance', 'board', 'gems',
                'tile_powers', 'player_hp', 'player_max_hp', 'player_offense',
                'player_damage_buffer', 'player_effects', 'enemy_name', 'enemy_hp',
                'enemy_max_hp', 'enemy_offense', 'enemy_damage_buffer',
                'enemy_effects', 'enemy_attacks', 'enemy_counters',
                'engine_rng', 'engine_rng_draw_index'):
        if key not in data:
            missing.append(key)
    if missing:
        raise ValueError(f'Missing required fields: {missing}')

    # Build identity
    _validate_build(data['build'])

    if not isinstance(data['session_id'], str) or not data['session_id']:
        raise ValueError('session_id must be a non-empty string')
    _require_int_nonneg(data['encounter_instance'], 'encounter_instance')

    # Board
    board = data['board']
    if not isinstance(board, str) or not _BOARD_RE.fullmatch(board):
        raise ValueError('board must match [A-Z]{4}(/[A-Z]{4}){3}')

    # Gems
    gems = tuple(data['gems'])
    if len(gems) != 16:
        raise ValueError('gems must have exactly 16 entries')
    if any(not isinstance(g, str) for g in gems):
        raise ValueError('each gem must be a string')

    # Tile powers
    tile_powers = tuple(data['tile_powers'])
    if len(tile_powers) != 16:
        raise ValueError('tile_powers must have exactly 16 entries')
    for tp in tile_powers:
        if not isinstance(tp, (int, float)) or isinstance(tp, bool) or not math.isfinite(tp):
            raise ValueError('tile_powers entries must be finite numbers')

    # Player
    _require_finite_nonneg(data['player_hp'], 'player_hp')
    _require_finite_nonneg(data['player_max_hp'], 'player_max_hp')
    if data['player_hp'] > data['player_max_hp']:
        raise ValueError('player_hp exceeds player_max_hp')
    _require_finite_nonneg(data['player_offense'], 'player_offense')
    _require_finite_nonneg(data['player_damage_buffer'], 'player_damage_buffer')
    if not isinstance(data['player_effects'], list):
        raise ValueError('player_effects must be a list')

    # Enemy
    if not isinstance(data['enemy_name'], str) or not data['enemy_name']:
        raise ValueError('enemy_name must be a non-empty string')
    _require_finite_nonneg(data['enemy_hp'], 'enemy_hp')
    _require_finite_nonneg(data['enemy_max_hp'], 'enemy_max_hp')
    if data['enemy_hp'] > data['enemy_max_hp']:
        raise ValueError('enemy_hp exceeds enemy_max_hp')
    _require_finite_nonneg(data['enemy_offense'], 'enemy_offense')
    _require_finite_nonneg(data['enemy_damage_buffer'], 'enemy_damage_buffer')
    if not isinstance(data['enemy_effects'], list):
        raise ValueError('enemy_effects must be a list')
    if not isinstance(data['enemy_attacks'], list):
        raise ValueError('enemy_attacks must be a list')
    counters = list(data['enemy_counters'])
    for c in counters:
        _require_int_nonneg(c, 'enemy_counters entry')
    if len(data['enemy_attacks']) != len(counters):
        raise ValueError(
            f"enemy_attacks (len {len(data['enemy_attacks'])}) and "
            f"enemy_counters (len {len(counters)}) must have equal length")
    normalised_attacks = []
    for i, attack in enumerate(data['enemy_attacks']):
        if not isinstance(attack, dict):
            raise ValueError(f'enemy_attacks[{i}] must be a dict')
        try:
            normalised = normalise_attack(attack)
        except ValueError as exc:
            raise ValueError(f'enemy_attacks[{i}]: {exc}')
        for req_key in ('min', 'max'):
            if req_key not in normalised:
                raise ValueError(
                    f'enemy_attacks[{i}] missing required key {req_key!r} after normalisation')
            v = normalised[req_key]
            if not isinstance(v, int) or isinstance(v, bool):
                raise ValueError(f'enemy_attacks[{i}][{req_key!r}] must be an integer')
        if 'rate_counter' in normalised:
            if normalised['rate_counter'] != counters[i]:
                raise ValueError(
                    f'enemy_attacks[{i}].rate_counter={normalised["rate_counter"]!r} '
                    f'conflicts with enemy_counters[{i}]={counters[i]!r}')
        normalised_attacks.append(normalised)

    # RNG
    _validate_engine_rng(data['engine_rng'])
    _require_int_nonneg(data['engine_rng_draw_index'], 'engine_rng_draw_index')

    # QRand (optional; must be None for ELIGIBLE)
    qrand_state = data.get('qrand_state', None)

    # Determine unsupported fields
    unsupported = []
    if any(g != 'none' for g in gems):
        unsupported.append('gems')
    if any(tp != 0.0 for tp in tile_powers):
        unsupported.append('tile_powers')
    if data['player_effects']:
        unsupported.append('player_effects')
    if data['enemy_effects']:
        unsupported.append('enemy_effects')
    if qrand_state is not None:
        unsupported.append('qrand_state')
    # mState preserved as native_state_raw; mapping to 'state' string is unconfirmed.
    if any('native_state_raw' in a for a in normalised_attacks):
        unsupported.append('attack_state_mapping_unconfirmed')

    return EncounterState(
        schema_version=ENCOUNTER_STATE_VERSION,
        build=dict(data['build']),
        session_id=data['session_id'],
        encounter_instance=data['encounter_instance'],
        board=board,
        gems=gems,
        tile_powers=tile_powers,
        player_hp=float(data['player_hp']),
        player_max_hp=float(data['player_max_hp']),
        player_offense=float(data['player_offense']),
        player_damage_buffer=float(data['player_damage_buffer']),
        player_effects=list(data['player_effects']),
        enemy_name=data['enemy_name'],
        enemy_hp=float(data['enemy_hp']),
        enemy_max_hp=float(data['enemy_max_hp']),
        enemy_offense=float(data['enemy_offense']),
        enemy_damage_buffer=float(data['enemy_damage_buffer']),
        enemy_effects=list(data['enemy_effects']),
        enemy_attacks=normalised_attacks,
        enemy_counters=counters,
        engine_rng={'words': list(data['engine_rng']['words']),
                    'cursor': data['engine_rng']['cursor']},
        engine_rng_draw_index=data['engine_rng_draw_index'],
        qrand_state=qrand_state,
        unsupported_fields=unsupported,
    )


def encounter_eligibility(state: EncounterState) -> EncounterEligibility:
    if state.unsupported_fields:
        return EncounterEligibility.UNSUPPORTED
    return EncounterEligibility.ELIGIBLE


def serialise(state: EncounterState) -> dict:
    """Return a JSON-safe dict representation."""
    return {
        'schema_version': state.schema_version,
        'build': state.build,
        'session_id': state.session_id,
        'encounter_instance': state.encounter_instance,
        'board': state.board,
        'gems': list(state.gems),
        'tile_powers': list(state.tile_powers),
        'player_hp': state.player_hp,
        'player_max_hp': state.player_max_hp,
        'player_offense': state.player_offense,
        'player_damage_buffer': state.player_damage_buffer,
        'player_effects': state.player_effects,
        'enemy_name': state.enemy_name,
        'enemy_hp': state.enemy_hp,
        'enemy_max_hp': state.enemy_max_hp,
        'enemy_offense': state.enemy_offense,
        'enemy_damage_buffer': state.enemy_damage_buffer,
        'enemy_effects': state.enemy_effects,
        'enemy_attacks': state.enemy_attacks,
        'enemy_counters': state.enemy_counters,
        'engine_rng': {'words': state.engine_rng['words'],
                       'cursor': state.engine_rng['cursor']},
        'engine_rng_draw_index': state.engine_rng_draw_index,
        'qrand_state': state.qrand_state,
        'unsupported_fields': state.unsupported_fields,
    }


def deserialise(data: dict) -> EncounterState:
    """Reconstruct an EncounterState from a serialised dict.

    Validates schema_version; raises ValueError on mismatch or bad data.
    """
    version = data.get('schema_version')
    if version != ENCOUNTER_STATE_VERSION:
        raise ValueError(
            f'schema_version {version!r} != {ENCOUNTER_STATE_VERSION} (current)')
    # Pass through to build_encounter_state for full validation, but preserve
    # qrand_state from the serialised form (may be None or non-None).
    state = build_encounter_state(data)
    # Restore unsupported_fields exactly as stored (build_encounter_state recomputes
    # them from the data, so they are already consistent).
    return state
