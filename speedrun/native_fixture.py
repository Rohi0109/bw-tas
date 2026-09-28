"""Schema for native encounter fixtures with provenance.

A fixture is an immutable record linking one attack boundary to:
  - build identity (EXE/PAK hashes),
  - session/encounter-instance/attack-id,
  - pre-submit state (from Lua scalar hook),
  - RNG draw interval [first_draw_index, last_draw_index],
  - post-turn observed state,
  - optional simulator prediction (kept separate for differential use).

Rules:
  - 'observed' fields must NEVER be used as simulator inputs.
  - 'unsupported' fields (effect queues, QRand) must appear in an explicit
    'unsupported_state' list; their absence fails eligibility.
  - Teacher-forced fixtures (recorded draw schedule used as input) must be
    labeled 'teacher_forced: true' and excluded from full-turn parity totals.
"""
import math
import re
from enum import Enum
from encounter_state import build_encounter_state, _BOARD_RE, _validate_engine_rng

SCHEMA_VERSION = 1

_REQUIRED_FIELDS = {
    'schema_version', 'build', 'session_id', 'encounter_instance',
    'attack_id', 'rng_interval', 'pre_submit', 'observed',
    'unsupported_state', 'teacher_forced',
}

_OPTIONAL_FIELDS = {'prediction'}

_BUILD_KEYS = {'BookwormAdventures.exe', 'main.pak'}


class FixtureEligibility(Enum):
    ELIGIBLE = 'eligible'
    UNSUPPORTED_STATE = 'unsupported_state'
    AMBIGUOUS_BOUNDARY = 'ambiguous_boundary'
    TEACHER_FORCED = 'teacher_forced'


def validate_fixture(fixture: dict) -> FixtureEligibility:
    """Validate fixture structure and return eligibility.

    Raises ValueError for any structural or type error.
    Does NOT check build hashes against a local installation.
    """
    if not isinstance(fixture, dict):
        raise ValueError('Fixture must be a dict')

    unknown = set(fixture) - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
    if unknown:
        raise ValueError(f'Unknown fixture fields: {unknown}')

    missing = _REQUIRED_FIELDS - set(fixture)
    if missing:
        raise ValueError(f'Missing required fixture fields: {missing}')

    if fixture['schema_version'] != SCHEMA_VERSION:
        raise ValueError(
            f'Unsupported schema_version {fixture["schema_version"]!r}; '
            f'expected {SCHEMA_VERSION}'
        )

    _validate_build(fixture['build'])
    _validate_string_field(fixture, 'session_id')
    _validate_int_field(fixture, 'encounter_instance', minimum=0)
    _validate_int_field(fixture, 'attack_id', minimum=0)
    _validate_rng_interval(fixture['rng_interval'])
    encounter = _validate_pre_submit(fixture['pre_submit'], fixture)
    _validate_observed(fixture['observed'])

    if not isinstance(fixture['unsupported_state'], list):
        raise ValueError('unsupported_state must be a list')
    if any(not isinstance(s, str) for s in fixture['unsupported_state']):
        raise ValueError('unsupported_state entries must be strings')

    if not isinstance(fixture['teacher_forced'], bool):
        raise ValueError('teacher_forced must be a bool')

    if 'prediction' in fixture and not isinstance(fixture['prediction'], dict):
        raise ValueError('prediction must be a dict when present')

    if fixture['teacher_forced']:
        return FixtureEligibility.TEACHER_FORCED
    # Derive unsupported from both the encounter snapshot and any caller annotation.
    if encounter.unsupported_fields or fixture['unsupported_state']:
        return FixtureEligibility.UNSUPPORTED_STATE
    return FixtureEligibility.ELIGIBLE


def validate_build_identity(fixture: dict, exe_hash: str, pak_hash: str) -> None:
    """Raise ValueError if fixture build hashes do not match the supplied hashes."""
    build = fixture.get('build', {})
    if not isinstance(build, dict):
        raise ValueError('Fixture build field is not a dict')
    if build.get('BookwormAdventures.exe') != exe_hash:
        raise ValueError(
            f'EXE hash mismatch: fixture={build.get("BookwormAdventures.exe")!r} '
            f'expected={exe_hash!r}'
        )
    if build.get('main.pak') != pak_hash:
        raise ValueError(
            f'PAK hash mismatch: fixture={build.get("main.pak")!r} '
            f'expected={pak_hash!r}'
        )


# --- Internal helpers ---

def _validate_build(build):
    if not isinstance(build, dict):
        raise ValueError('build must be a dict')
    missing = _BUILD_KEYS - set(build)
    if missing:
        raise ValueError(f'build missing keys: {missing}')
    for key in _BUILD_KEYS:
        value = build[key]
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f'build[{key!r}] must be a 64-char hex string')
        try:
            int(value, 16)
        except ValueError:
            raise ValueError(f'build[{key!r}] is not a valid hex string')


def _validate_string_field(fixture, name):
    value = fixture[name]
    if not isinstance(value, str) or not value:
        raise ValueError(f'{name} must be a non-empty string')


def _validate_int_field(fixture, name, minimum=0):
    value = fixture[name]
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')


def _validate_rng_interval(interval):
    if not isinstance(interval, dict):
        raise ValueError('rng_interval must be a dict')
    for key in ('first', 'last'):
        if key not in interval:
            raise ValueError(f'rng_interval missing key: {key!r}')
        value = interval[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f'rng_interval[{key!r}] must be a non-negative integer')
    if interval['first'] > interval['last']:
        raise ValueError(
            f'rng_interval first ({interval["first"]}) must not exceed '
            f'last ({interval["last"]})'
        )


_OBSERVED_REQUIRED = {'player_hp', 'enemy_hp', 'board', 'rng_snapshot'}


_ACTION_RE = re.compile(r'[A-Z]{2,}')


def _validate_action_against_board(board: str, action: str) -> None:
    """Reject actions whose letters cannot be formed from available board tiles."""
    from collections import Counter
    tiles = board.replace('/', '')
    if len(action) > len(tiles):
        raise ValueError(
            f"selected_action length {len(action)} exceeds board tile count {len(tiles)}")
    tile_counts = Counter(tiles)
    action_counts = Counter(action)
    for letter, needed in action_counts.items():
        available = tile_counts.get(letter, 0)
        if needed > available:
            raise ValueError(
                f"selected_action needs {needed}x '{letter}' but board has {available}")


def _validate_pre_submit(pre_submit: dict, fixture: dict):
    """Validate pre_submit as a supported encounter snapshot; return the EncounterState.

    Reuses the encounter_state contract (build_encounter_state) so validation
    rules are defined once. Augments pre_submit with fixture-level provenance
    (build, session_id, encounter_instance) before calling build_encounter_state.
    selected_action is additionally validated against the captured board.
    """
    if not isinstance(pre_submit, dict):
        raise ValueError('pre_submit must be a dict')
    # Augment with fixture provenance so build_encounter_state can validate build identity.
    augmented = dict(pre_submit)
    # Use fixture-level provenance as the authority; reject conflicts silently relabelled.
    for key in ('build', 'session_id', 'encounter_instance'):
        fixture_val = fixture.get(key)
        if key in pre_submit and pre_submit[key] != fixture_val:
            raise ValueError(
                f"pre_submit[{key!r}] conflicts with fixture-level {key!r}: "
                f"{pre_submit[key]!r} != {fixture_val!r}")
        augmented[key] = fixture_val
    try:
        encounter = build_encounter_state(augmented)
    except ValueError as exc:
        raise ValueError(f'pre_submit failed encounter-state validation: {exc}')
    # Validate selected_action: 2+ uppercase letters, must be formable from the board.
    action = pre_submit.get('selected_action')
    if not isinstance(action, str) or not _ACTION_RE.fullmatch(action):
        raise ValueError(
            "pre_submit['selected_action'] must be 2+ uppercase letters (A-Z only); "
            f"got {action!r}")
    _validate_action_against_board(pre_submit['board'], action)
    return encounter


def _validate_observed(observed: dict) -> None:
    """Validate observed after-state; requires board and RNG for full-turn replay."""
    if not isinstance(observed, dict):
        raise ValueError('observed must be a dict')
    missing = _OBSERVED_REQUIRED - set(observed)
    if missing:
        raise ValueError(f'observed missing required fields: {missing}')
    for key in ('player_hp', 'enemy_hp'):
        v = observed[key]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(f'observed[{key!r}] must be a number')
        if not math.isfinite(v):
            raise ValueError(f'observed[{key!r}] must be finite, got {v!r}')
        if v < 0:
            raise ValueError(f'observed[{key!r}] must be non-negative, got {v!r}')
    board = observed['board']
    if not isinstance(board, str) or not _BOARD_RE.fullmatch(board):
        raise ValueError("observed['board'] must match [A-Z]{4}(/[A-Z]{4}){3}")
    _validate_engine_rng(observed['rng_snapshot'], 'observed.rng_snapshot')
