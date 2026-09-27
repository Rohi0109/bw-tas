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
from enum import Enum

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
    _validate_pre_submit(fixture['pre_submit'])
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
    if fixture['unsupported_state']:
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


_PRE_SUBMIT_REQUIRED = {'player_hp', 'enemy_hp'}
_OBSERVED_REQUIRED = {'player_hp', 'enemy_hp'}


def _validate_pre_submit(pre_submit):
    if not isinstance(pre_submit, dict):
        raise ValueError('pre_submit must be a dict')
    missing = _PRE_SUBMIT_REQUIRED - set(pre_submit)
    if missing:
        raise ValueError(f'pre_submit missing required fields: {missing}')
    for key in _PRE_SUBMIT_REQUIRED:
        if not isinstance(pre_submit[key], (int, float)) or isinstance(pre_submit[key], bool):
            raise ValueError(f'pre_submit[{key!r}] must be a number')


def _validate_observed(observed):
    if not isinstance(observed, dict):
        raise ValueError('observed must be a dict')
    missing = _OBSERVED_REQUIRED - set(observed)
    if missing:
        raise ValueError(f'observed missing required fields: {missing}')
