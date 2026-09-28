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


def group_log_attacks(fields: dict, owner_filter: 'str | None' = None) -> list[dict]:
    """Extract and group ATTACK sub-field entries from a ParsedRecord.fields dict.

    The parser stores each ATTACK row under a tuple key:
        ('ATTACK', owner, atk_key, field_name) -> value_string

    Owner strings used by the parser / DumpSimulationState.lua:
        'enemy'  — enemy attacks (the set the AI chooses from)
        'player' — player attacks (not used by the AI model; excluded by default)

    Args:
        fields:       ParsedRecord.fields dict with tuple keys.
        owner_filter: When given, only return attack dicts for this owner string.
                      Pass 'enemy' to exclude player attacks.  None returns all owners.

    This function collects all matching entries, groups them by (owner, atk_key),
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
        if owner_filter is not None and owner != owner_filter:
            continue
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
                Also carries optional classification flags:
                    teacher_forced (bool, default False)
                    unsupported_state (list of str, default [])
                Any of these may be absent; missing entries are not synthesised
                (the caller should mark the resulting fixture incomplete).

    Returns:
        A dict passable to validate_fixture.  Any required field absent from
        fields or extra is omitted — do NOT synthesise missing data to reach
        eligibility.

    Notes on per-record provenance (selected_action, rng_interval, observed):
        These values apply to a specific attack boundary.  If the caller supplies
        multiple records from the same log file, each record may need different
        values.  The caller is responsible for providing the correct extra dict per
        record.  assemble_captures_from_log passes the same extra to all records
        in a file; callers with per-record variation should call
        assemble_encounter_from_fields directly with a per-record extra dict.

    Notes on attack_id:
        If extra contains 'attack_id', it is compared against the parser's
        rec.attack_id (when the caller passes it as extra['_rec_attack_id']).
        A conflict raises ValueError.

    Notes on enemy_counters derivation:
        After convert+normalise, each attack dict may contain 'rate_counter'
        (the captured mRateCounter value).  enemy_counters is derived from
        these values in the same order as enemy_attacks.  If an attack is
        missing mRateCounter in the log, 'attack_counter_missing' is added to
        unsupported_fields and enemy_counters is NOT derived (so validate_fixture
        can reject the incomplete fixture properly).
    """
    # Collect unsupported reasons discovered during assembly.
    # These will be MERGED with extra.get('unsupported_state', []) at the end.
    assembly_unsupported: list[str] = []

    # -----------------------------------------------------------------------
    # Finding 3: Only group enemy attacks — exclude player attacks.
    # Parser owner strings: 'enemy' for enemy attacks, 'player' for player attacks.
    # -----------------------------------------------------------------------
    raw_attacks = group_log_attacks(fields, owner_filter='enemy')

    # Strip the internal metadata keys before passing to assemble_hook_attacks.
    hook_attack_dicts = [
        {k: v for k, v in atk.items() if not k.startswith('_')}
        for atk in raw_attacks
    ]

    # Convert string-valued hook fields to native Python types.
    typed_attacks = assemble_hook_attacks(hook_attack_dicts)

    # -----------------------------------------------------------------------
    # Finding 2 (mRateCounter): Require mRateCounter per attack; do not default to 0.
    # assemble_hook_attacks calls convert_hook_attack_types (not normalise_attack),
    # so the key is still 'mRateCounter' (as int after type conversion).
    # -----------------------------------------------------------------------
    counter_missing = any('mRateCounter' not in atk for atk in typed_attacks)
    if counter_missing:
        assembly_unsupported.append('attack_counter_missing')
        enemy_counters = None  # omit from pre_submit; validate_fixture will reject
    else:
        enemy_counters = [int(atk['mRateCounter']) for atk in typed_attacks]

    # --- Build pre_submit dict ---
    pre_submit: dict = {}

    # -----------------------------------------------------------------------
    # Finding 1: Extract creature fields using actual Lua hook field names.
    # DumpSimulationState.lua emits: mHealth, mMaxHealth, mName,
    #   mDamageBuffer, mOffenseBonusPct, mState.
    # Key format: ('CREATURE', owner, lua_field_name) -> value_string
    # -----------------------------------------------------------------------
    # Map: (owner, lua_field_name) -> pre_submit key
    _creature_field_map = {
        ('player', 'mHealth'):          'player_hp',
        ('player', 'mMaxHealth'):       'player_max_hp',
        ('player', 'mOffenseBonusPct'): 'player_offense',
        ('player', 'mDamageBuffer'):    'player_damage_buffer',
        ('enemy',  'mHealth'):          'enemy_hp',
        ('enemy',  'mMaxHealth'):       'enemy_max_hp',
        ('enemy',  'mOffenseBonusPct'): 'enemy_offense',
        ('enemy',  'mDamageBuffer'):    'enemy_damage_buffer',
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

    # Enemy name: ('CREATURE', 'enemy', 'mName') -> str
    enemy_name_raw = creature_raw.get(('enemy', 'mName'))
    if enemy_name_raw is not None:
        pre_submit['enemy_name'] = enemy_name_raw

    # -----------------------------------------------------------------------
    # Engine RNG: stored under tuple keys.
    # Format: ('ENGINE_RNG', 'words', str_index) -> uint32_str
    #         ('ENGINE_RNG', 'cursor') -> int_str
    #         ('ENGINE_RNG', 'draw_index') -> int_str
    # Finding 2 (RNG): Require all 624 indexed word entries.
    # If any are missing, add 'rng_incomplete' and omit engine_rng from pre_submit.
    # -----------------------------------------------------------------------
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

    if rng_cursor is not None:
        # Check all 624 words are present (indices 0..623).
        missing_words = [i for i in range(624) if i not in rng_words_raw]
        if missing_words:
            assembly_unsupported.append('rng_incomplete')
            # Do NOT add engine_rng to pre_submit; leave it absent so validate_fixture rejects.
        else:
            words = [rng_words_raw[i] for i in range(624)]
            pre_submit['engine_rng'] = {'words': words, 'cursor': rng_cursor}
    elif rng_words_raw:
        # Words present but cursor absent → incomplete.
        assembly_unsupported.append('rng_incomplete')

    if rng_draw_index is not None:
        pre_submit['engine_rng_draw_index'] = rng_draw_index

    # -----------------------------------------------------------------------
    # Board: stored as ('BOARD',) tuple key.
    # The parser does NOT emit a dimensionless BOARD key; this is a placeholder
    # for a board format that uses a single flat value (if the Lua hook is updated
    # to emit it).  Currently the hook does not emit BOARD rows, so this will
    # normally be absent.
    # -----------------------------------------------------------------------
    for k, v in fields.items():
        if isinstance(k, tuple) and k[0] == 'BOARD' and len(k) == 1:
            pre_submit['board'] = v

    # -----------------------------------------------------------------------
    # Gems and tile_powers: stored as per-tile tuples.
    # ('GEMS', str_index) -> gem_type_str
    # ('TILE_POWERS', str_index) -> float_str
    # Finding 2 (tile data): If present but incomplete, add 'tile_data_incomplete'.
    # -----------------------------------------------------------------------
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

    if gems_raw:
        if len(gems_raw) == 16:
            pre_submit['gems'] = [gems_raw[i] for i in range(16)]
        else:
            assembly_unsupported.append('tile_data_incomplete')

    if tile_powers_raw:
        if len(tile_powers_raw) == 16:
            pre_submit['tile_powers'] = [tile_powers_raw[i] for i in range(16)]
        else:
            if 'tile_data_incomplete' not in assembly_unsupported:
                assembly_unsupported.append('tile_data_incomplete')

    # -----------------------------------------------------------------------
    # Finding 2 (EFFECT rows): If any EFFECT tuple keys are present, mark unsupported.
    # The hook only emits an UNSUPPORTED marker for effect queues — it is not a
    # reliable signal that effects are actually empty.  We default both to [] but
    # mark them unsupported so the fixture is not promoted to eligible.
    # -----------------------------------------------------------------------
    effect_keys_present = any(
        isinstance(k, tuple) and k[0] == 'EFFECT'
        for k in fields
    )
    if effect_keys_present:
        assembly_unsupported.append('effects_unsupported')

    pre_submit['player_effects'] = []
    pre_submit['enemy_effects'] = []

    # Attach attacks and counters.
    pre_submit['enemy_attacks'] = typed_attacks
    if enemy_counters is not None:
        pre_submit['enemy_counters'] = enemy_counters

    # selected_action comes from extra (cannot be derived from the log).
    if 'selected_action' in extra:
        pre_submit['selected_action'] = extra['selected_action']

    # --- Build the top-level fixture dict ---
    fixture: dict = {}

    # -----------------------------------------------------------------------
    # Finding 4: Provenance from extra — preserve teacher_forced and unsupported_state.
    # -----------------------------------------------------------------------
    for key in ('schema_version', 'build', 'session_id', 'encounter_instance',
                'rng_interval', 'observed'):
        if key in extra:
            fixture[key] = extra[key]

    # Finding 4: attack_id — use extra['attack_id'] if present; also check for
    # '_rec_attack_id' from the parser record and raise on conflict.
    rec_attack_id = extra.get('_rec_attack_id')
    extra_attack_id = extra.get('attack_id')
    if rec_attack_id is not None and extra_attack_id is not None:
        if rec_attack_id != extra_attack_id:
            raise ValueError(
                f'attack_id conflict: extra has {extra_attack_id!r} but '
                f'parsed record has {rec_attack_id!r}')
    if extra_attack_id is not None:
        fixture['attack_id'] = extra_attack_id
    elif rec_attack_id is not None:
        fixture['attack_id'] = rec_attack_id

    # Finding 4: Preserve teacher_forced from extra (do NOT default unconditionally).
    fixture['teacher_forced'] = extra.get('teacher_forced', False)

    # Finding 4: Merge unsupported_state from extra with assembly-discovered reasons.
    # Do NOT replace one with the other; merge both sets.
    caller_unsupported = list(extra.get('unsupported_state', []))
    merged_unsupported = list(caller_unsupported)
    for reason in assembly_unsupported:
        if reason not in merged_unsupported:
            merged_unsupported.append(reason)
    fixture['unsupported_state'] = merged_unsupported

    fixture['pre_submit'] = pre_submit

    return fixture


def assemble_captures_from_log(log_path: str, extra: dict) -> dict:
    """Read log_path with parse_sim_log, assemble fixtures, validate each.

    Args:
        log_path:  Path to a captured GDB+Lua game log file.
        extra:     Provenance dict passed through to assemble_encounter_from_fields.
                   Keys: schema_version, build, session_id, encounter_instance,
                   attack_id, rng_interval, selected_action, observed.
                   Optional keys: teacher_forced (bool), unsupported_state (list).

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

    Note on per-record extra values (selected_action, rng_interval, observed,
    attack_id): These values apply to a specific attack boundary.  When multiple
    records are parsed from the same log file, each may need different values.
    This function passes the same extra dict to all records; callers with
    per-record variation should call assemble_encounter_from_fields directly
    with a per-record extra dict (one per record).

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
            # Pass the parser's record attack_id so assemble_encounter_from_fields
            # can detect conflicts with extra['attack_id'].
            rec_extra = dict(extra, _rec_attack_id=rec.attack_id)
            fixture = assemble_encounter_from_fields(rec.fields, rec_extra)
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
