"""Production entry point connecting capture_log_parser → attack grouping →
type conversion → encounter validation.

Pipeline:
  parse_sim_log(lines)               # automation/capture_log_parser.py
  → partition_sim_log(records)       # split good vs quarantined
  → group_log_attacks(fields)        # group tuple-keyed ATTACK entries per attack
  → assemble_hook_attacks(raw_atks)  # convert string types (native_enemy_ai.py)
  → assemble_encounter_from_fields   # build fixture-compatible dict
  → validate_fixture                 # native_fixture.py
"""
import sys
import os

# Ensure automation/ is importable when running with PYTHONPATH=speedrun
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'automation'))

from capture_log_parser import parse_sim_log, partition_sim_log
from native_enemy_ai import assemble_hook_attacks, normalise_attack
from native_fixture import validate_fixture

# ---------------------------------------------------------------------------
# CREATURE field names used in the log
# ---------------------------------------------------------------------------

# Numeric creature sub-fields that must be converted from string to float/int.
_CREATURE_FLOAT_FIELDS = frozenset({
    'player_hp', 'player_max_hp', 'player_offense', 'player_damage_buffer',
    'enemy_hp', 'enemy_max_hp', 'enemy_offense', 'enemy_damage_buffer',
})
_CREATURE_INT_FIELDS = frozenset()  # none needed currently


def _to_float_safe(v: str, name: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{name}: cannot convert {v!r} to float')


def group_log_attacks(fields: dict) -> list[dict]:
    """Extract and group ATTACK sub-field entries from a ParsedRecord.fields dict.

    The parser stores each ATTACK row under a tuple key:
        ('ATTACK', owner, atk_key, field_name) -> value_string

    This function collects all such entries, groups them by (owner, atk_key),
    and returns a list of raw string-valued attack dicts sorted by (owner, atk_key)
    for stable ordering.  Each dict maps field_name -> value_string and also
    carries '_owner' and '_atk_key' metadata so callers can derive enemy_counters
    from 'mRateCounter' after type conversion.

    The '_owner' and '_atk_key' keys are prefixed with '_' to avoid collision
    with Lua hook field names (which are camelCase starting with 'm').
    """
    # Collect (owner, atk_key) pairs preserving first-seen order for stable sort.
    grouped: dict[tuple, dict] = {}
    for k, v in fields.items():
        if not (isinstance(k, tuple) and len(k) == 4 and k[0] == 'ATTACK'):
            continue
        _, owner, atk_key, field_name = k
        slot_key = (owner, atk_key)
        if slot_key not in grouped:
            grouped[slot_key] = {'_owner': owner, '_atk_key': atk_key}
        grouped[slot_key][field_name] = v

    return [grouped[key] for key in sorted(grouped)]


def assemble_encounter_from_fields(fields: dict, extra: dict) -> dict:
    """Build a fixture-compatible dict from a ParsedRecord.fields dict and provenance.

    Args:
        fields: ParsedRecord.fields — a dict with tuple keys as produced by
                parse_sim_log.  Required CREATURE fields supply player/enemy
                stats; ATTACK tuple keys supply attack sub-fields.
        extra:  Provenance and annotation dict containing fields that cannot
                come from the log alone:
                    schema_version, build, session_id, encounter_instance,
                    attack_id, rng_interval, selected_action, observed.
                Any of these may be absent; missing entries are not synthesised
                (the caller should mark the resulting fixture incomplete).

    Returns:
        A dict passable to validate_fixture.  Any required field absent from
        fields or extra is omitted — do NOT synthesise missing data to reach
        eligibility.

    Notes on enemy_counters derivation:
        After convert+normalise, each attack dict may contain 'rate_counter'
        (the captured mRateCounter value).  enemy_counters is derived from
        these values in the same order as enemy_attacks.  If an attack has no
        mRateCounter in the log, we default to 0 (the counter was at its
        initial/reset state when captured; this is a documented assumption
        rather than synthesised data, since 0 is the only safe default that
        does not promote eligibility artificially).

        build_encounter_state validates that each attack's rate_counter matches
        the parallel enemy_counters entry, so any inconsistency will surface
        as a ValueError rather than being silently accepted.
    """
    # --- Extract raw attack dicts from ATTACK tuple keys ---
    raw_attacks = group_log_attacks(fields)

    # Strip the internal metadata keys before passing to assemble_hook_attacks.
    hook_attack_dicts = [
        {k: v for k, v in atk.items() if not k.startswith('_')}
        for atk in raw_attacks
    ]

    # Convert string-valued hook fields to native Python types.
    typed_attacks = assemble_hook_attacks(hook_attack_dicts)

    # Derive enemy_counters from mRateCounter in each typed attack dict.
    # assemble_hook_attacks calls convert_hook_attack_types (not normalise_attack),
    # so the key is still 'mRateCounter' (as int after type conversion), not 'rate_counter'.
    # Default to 0 when mRateCounter was absent in the log (see docstring).
    enemy_counters = [int(atk.get('mRateCounter', 0)) for atk in typed_attacks]

    # --- Build pre_submit dict ---
    pre_submit: dict = {}

    # Extract creature fields from CREATURE tuple keys.
    # Key format: ('CREATURE', owner, field_name) -> value_string
    # We look for well-known scalar field names that map directly.
    _creature_field_map = {
        # (owner_prefix, lua_field_name) -> pre_submit key
        ('player', 'player_hp'):             'player_hp',
        ('player', 'player_max_hp'):         'player_max_hp',
        ('player', 'player_offense'):        'player_offense',
        ('player', 'player_damage_buffer'):  'player_damage_buffer',
        ('enemy',  'enemy_hp'):              'enemy_hp',
        ('enemy',  'enemy_max_hp'):          'enemy_max_hp',
        ('enemy',  'enemy_offense'):         'enemy_offense',
        ('enemy',  'enemy_damage_buffer'):   'enemy_damage_buffer',
    }

    # Gather all CREATURE fields into a flat lookup: (owner, field_name) -> value_str
    creature_raw: dict = {}
    for k, v in fields.items():
        if isinstance(k, tuple) and len(k) == 3 and k[0] == 'CREATURE':
            _, owner, field_name = k
            creature_raw[(owner, field_name)] = v

    # Map to pre_submit; convert numeric fields.
    for (owner, lua_name), dest_key in _creature_field_map.items():
        raw_val = creature_raw.get((owner, lua_name))
        if raw_val is not None:
            if dest_key in _CREATURE_FLOAT_FIELDS:
                pre_submit[dest_key] = _to_float_safe(raw_val, dest_key)
            else:
                pre_submit[dest_key] = raw_val

    # Engine RNG: stored under a tuple key ('ENGINE_RNG', ...) or CREATURE rows.
    # Look for engine_rng sub-fields: ('ENGINE_RNG', 'words', idx) and ('ENGINE_RNG', 'cursor').
    # Format: ('ENGINE_RNG', 'words', str_index) -> uint32_str
    #         ('ENGINE_RNG', 'cursor') -> int_str
    rng_words_raw: dict[int, int] = {}
    rng_cursor: int | None = None
    rng_draw_index: int | None = None
    for k, v in fields.items():
        if not isinstance(k, tuple):
            continue
        if k[0] == 'ENGINE_RNG':
            if len(k) == 3 and k[1] == 'words':
                try:
                    idx = int(k[2])
                    rng_words_raw[idx] = int(v)
                except (ValueError, TypeError):
                    pass
            elif len(k) == 2 and k[1] == 'cursor':
                try:
                    rng_cursor = int(v)
                except (ValueError, TypeError):
                    pass
            elif len(k) == 2 and k[1] == 'draw_index':
                try:
                    rng_draw_index = int(v)
                except (ValueError, TypeError):
                    pass

    if rng_words_raw and rng_cursor is not None:
        # Reconstruct ordered words list (indices 0..623)
        words = [rng_words_raw.get(i, 0) for i in range(624)]
        pre_submit['engine_rng'] = {'words': words, 'cursor': rng_cursor}

    if rng_draw_index is not None:
        pre_submit['engine_rng_draw_index'] = rng_draw_index

    # Board: stored as ('BOARD',) or under a known CREATURE key.
    for k, v in fields.items():
        if isinstance(k, tuple) and k[0] == 'BOARD' and len(k) == 1:
            pre_submit['board'] = v

    # Gems and tile_powers: stored as per-tile tuples.
    # ('GEMS', str_index) -> gem_type_str
    # ('TILE_POWERS', str_index) -> float_str
    gems_raw: dict[int, str] = {}
    tile_powers_raw: dict[int, float] = {}
    for k, v in fields.items():
        if not isinstance(k, tuple):
            continue
        if k[0] == 'GEMS' and len(k) == 2:
            try:
                gems_raw[int(k[1])] = v
            except (ValueError, TypeError):
                pass
        elif k[0] == 'TILE_POWERS' and len(k) == 2:
            try:
                tile_powers_raw[int(k[1])] = float(v)
            except (ValueError, TypeError):
                pass

    if len(gems_raw) == 16:
        pre_submit['gems'] = [gems_raw.get(i, 'none') for i in range(16)]
    if len(tile_powers_raw) == 16:
        pre_submit['tile_powers'] = [tile_powers_raw.get(i, 0.0) for i in range(16)]

    # Enemy name: ('CREATURE', 'enemy', 'enemy_name') -> str
    enemy_name_raw = creature_raw.get(('enemy', 'enemy_name'))
    if enemy_name_raw is not None:
        pre_submit['enemy_name'] = enemy_name_raw

    # Effects: default to empty lists (no native capture of effect queues yet;
    # non-empty effects would be an UNSUPPORTED marker in the log, which quarantines
    # the block before we ever reach assemble_encounter_from_fields).
    pre_submit.setdefault('player_effects', [])
    pre_submit.setdefault('enemy_effects', [])

    # Attach attacks and counters.
    pre_submit['enemy_attacks'] = typed_attacks
    pre_submit['enemy_counters'] = enemy_counters

    # selected_action comes from extra (cannot be derived from the log).
    if 'selected_action' in extra:
        pre_submit['selected_action'] = extra['selected_action']

    # --- Build the top-level fixture dict ---
    fixture: dict = {}

    # Provenance from extra.
    for key in ('schema_version', 'build', 'session_id', 'encounter_instance',
                'attack_id', 'rng_interval', 'observed'):
        if key in extra:
            fixture[key] = extra[key]

    # teacher_forced default: False (live captures are not teacher-forced).
    fixture.setdefault('teacher_forced', False)

    # unsupported_state: start empty; build_encounter_state will populate
    # unsupported_fields (including attack_state_mapping_unconfirmed when
    # native_state_raw is present) once pre_submit is validated.
    fixture.setdefault('unsupported_state', [])

    fixture['pre_submit'] = pre_submit

    return fixture


def assemble_captures_from_log(log_path: str, extra: dict) -> dict:
    """Read log_path with parse_sim_log, assemble fixtures, validate each.

    Args:
        log_path:  Path to a captured GDB+Lua game log file.
        extra:     Provenance dict passed through to assemble_encounter_from_fields.
                   Keys: schema_version, build, session_id, encounter_instance,
                   attack_id, rng_interval, selected_action, observed.

    Returns:
        {
            'valid': [
                {
                    'fixture': <fixture dict>,
                    'eligibility': <FixtureEligibility.value string>,
                    'unsupported_fields': <list of str>,
                }
            ],
            'quarantined': [
                {'reason': <str>, 'raw': <str repr of ParsedRecord>},
            ],
        }

    For each valid parsed record, calls assemble_encounter_from_fields then
    validate_fixture.  unsupported_fields are passed through without modification.
    Quarantined records are preserved with their reason strings — not dropped.

    If assemble_encounter_from_fields or validate_fixture raises ValueError (e.g.
    due to a counter conflict or incomplete fields), the record is added to
    'valid' with eligibility='error' and the error string in 'unsupported_fields'
    rather than crashing the whole pipeline.
    """
    with open(log_path, 'r', encoding='utf-8', errors='replace') as fh:
        lines = fh.readlines()

    all_records = parse_sim_log(lines)
    good_records, quarantined_records = partition_sim_log(all_records)

    result: dict = {'valid': [], 'quarantined': []}

    for rec in quarantined_records:
        result['quarantined'].append({
            'reason': rec.quarantine_reason,
            'raw': repr(rec),
        })

    for rec in good_records:
        try:
            fixture = assemble_encounter_from_fields(rec.fields, extra)
            eligibility_obj = validate_fixture(fixture)
            # Recover unsupported_fields from the encounter state built during validation.
            # validate_fixture calls build_encounter_state internally; we need to re-derive
            # unsupported_fields by inspecting the normalised attacks in the fixture.
            normalised_atks = []
            for atk in fixture.get('pre_submit', {}).get('enemy_attacks', []):
                try:
                    normalised_atks.append(normalise_attack(atk))
                except ValueError:
                    pass
            unsupported_fields: list[str] = list(fixture.get('unsupported_state', []))
            if any('native_state_raw' in a for a in normalised_atks):
                if 'attack_state_mapping_unconfirmed' not in unsupported_fields:
                    unsupported_fields.append('attack_state_mapping_unconfirmed')
            result['valid'].append({
                'fixture': fixture,
                'eligibility': eligibility_obj.value,
                'unsupported_fields': unsupported_fields,
            })
        except ValueError as exc:
            result['valid'].append({
                'fixture': None,
                'eligibility': 'error',
                'unsupported_fields': [str(exc)],
            })

    return result
