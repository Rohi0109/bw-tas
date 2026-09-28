"""Assemble immutable capture evidence into validated, boundary-specific fixtures.

The Lua log does not contain board/RNG snapshots. Supply these as captured_state
in a sidecar bound to the same attack ID; never infer them from observed outcomes.
Unknown native semantics remain unsupported, even when a fixture is complete.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'automation'))
from capture_log_parser import parse_sim_log, partition_sim_log
from native_enemy_ai import assemble_hook_attacks
from native_fixture import validate_fixture
from encounter_state import build_encounter_state

# Only inputs absent from the scalar hook may be joined from a captured sidecar.
_JOIN_FIELDS = {'board', 'gems', 'tile_powers', 'engine_rng',
                'engine_rng_draw_index', 'qrand_state'}


def group_log_attacks(fields, owner_filter=None):
    grouped = {}
    for key, value in fields.items():
        if len(key) != 4 or key[0] != 'ATTACK':
            continue
        _, owner, attack_key, name = key
        if owner_filter is not None and owner != owner_filter:
            continue
        slot = grouped.setdefault((owner, attack_key),
                                  {'_owner': owner, '_atk_key': attack_key})
        slot[name] = value
    # This is a deterministic serialization order, NOT a native selection order.
    return [grouped[key] for key in sorted(grouped)]


def _indexed(fields, kind, size, convert, prefix=()):
    values = {}
    for key, value in fields.items():
        if key[:1 + len(prefix)] != (kind,) + prefix:
            continue
        if len(key) != len(prefix) + 2:
            raise ValueError(f'malformed {kind} index')
        index = key[-1]
        if not isinstance(index, str) or not index.isdecimal() or str(int(index)) != index:
            raise ValueError(f'invalid {kind} index {index!r}')
        index = int(index)
        if not 0 <= index < size:
            raise ValueError(f'{kind} index outside 0..{size - 1}')
        values[index] = convert(value)
    if not values:
        return None
    if set(values) != set(range(size)):
        return None
    return [values[i] for i in range(size)]


def assemble_encounter_from_fields(fields, extra):
    """Assemble one boundary; missing inputs stay missing, raw state stays raw."""
    for key in fields:
        if key[0] in ('CREATURE', 'ATTACK', 'EFFECT', 'COLLECTION') and key[1] not in ('player', 'enemy'):
            raise ValueError(f'unknown capture owner {key[1]!r}')
    reasons = extra.get('unsupported_state', [])
    if not isinstance(reasons, list) or any(not isinstance(x, str) for x in reasons):
        raise ValueError('unsupported_state must be a list of strings')
    reasons = list(reasons)
    pre = {}
    raw_attacks = group_log_attacks(fields, 'enemy')
    typed = assemble_hook_attacks([
        {k: v for k, v in attack.items() if not k.startswith('_')}
        for attack in raw_attacks])
    pre['enemy_attacks'] = typed
    pre['enemy_attack_keys'] = [a['_atk_key'] for a in raw_attacks]
    if all('mRateCounter' in attack for attack in typed):
        pre['enemy_counters'] = [a['mRateCounter'] for a in typed]
    else:
        reasons.append('attack_counter_missing')
    if typed:
        reasons.append('attack_order_unconfirmed')
    count = fields.get(('COLLECTION', 'enemy', 'attacks'))
    if count is None:
        reasons.append('enemy_attack_presence_unconfirmed')
    elif not count.isdecimal() or int(count) != len(typed):
        raise ValueError('enemy attack count disagrees with captured entries')

    scalar_map = {'mHealth': 'hp', 'mMaxHealth': 'max_hp',
                  'mDamageBuffer': 'damage_buffer', 'mOffenseBonusPct': 'offense'}
    for owner in ('player', 'enemy'):
        for native, dest in scalar_map.items():
            value = fields.get(('CREATURE', owner, native))
            if value is not None:
                pre[f'{owner}_{dest}'] = float(value)
        # Preserve native percentages without claiming a validated simulator mapping.
        if ('CREATURE', owner, 'mOffenseBonusPct') in fields:
            reasons.append('offense_mapping_unconfirmed')
        native_state = fields.get(('CREATURE', owner, 'mState'))
        if native_state is not None:
            pre[f'{owner}_native_state_raw'] = native_state
            reasons.append('creature_state_mapping_unconfirmed')
        effects = {}
        for key, value in fields.items():
            if len(key) == 4 and key[:2] == ('EFFECT', owner):
                effects.setdefault(key[2], {})[key[3]] = value
        pre[f'{owner}_effects'] = [dict(native_key=k, **v) for k, v in sorted(effects.items())]
        if effects:
            reasons.append('effects_unsupported')
        count = fields.get(('COLLECTION', owner, 'effects'))
        if count is None:
            reasons.append(f'{owner}_effect_presence_unconfirmed')
        elif not count.isdecimal() or int(count) != len(effects):
            raise ValueError(f'{owner} effect count disagrees with captured entries')
    name = fields.get(('CREATURE', 'enemy', 'mName'))
    if name is not None:
        pre['enemy_name'] = name

    words = _indexed(fields, 'ENGINE_RNG', 624, int, ('words',))
    cursor = fields.get(('ENGINE_RNG', 'cursor'))
    if words is not None and cursor is not None:
        pre['engine_rng'] = {'words': words, 'cursor': int(cursor)}
    elif any(key[0] == 'ENGINE_RNG' for key in fields):
        reasons.append('rng_incomplete')
    draw_index = fields.get(('ENGINE_RNG', 'draw_index'))
    if draw_index is not None:
        pre['engine_rng_draw_index'] = int(draw_index)
    # Dimensionless BOARD rows are supported by the parser. The current hook
    # does not emit them; live captures normally join board data from a sidecar.
    if ('BOARD',) in fields:
        pre['board'] = fields[('BOARD',)]
    for kind, dest, convert in (('GEMS', 'gems', str), ('TILE_POWERS', 'tile_powers', float)):
        values = _indexed(fields, kind, 16, convert)
        if values is not None:
            pre[dest] = values
        elif any(key[0] == kind for key in fields):
            reasons.append('tile_data_incomplete')

    captured = extra.get('captured_state', {})
    if not isinstance(captured, dict) or set(captured) - _JOIN_FIELDS:
        raise ValueError('captured_state contains unknown or hook-owned fields')
    for key, value in captured.items():
        if key in pre and pre[key] != value:
            raise ValueError(f'captured_state conflicts with log field {key}')
        # Do not let a sidecar conceal partial/invalid inline capture data.
        if key == 'engine_rng' and 'rng_incomplete' in reasons:
            raise ValueError('cannot replace incomplete inline RNG with sidecar state')
        if key in ('gems', 'tile_powers') and 'tile_data_incomplete' in reasons:
            raise ValueError('cannot replace incomplete inline tiles with sidecar state')
        pre[key] = copy.deepcopy(value)
    if 'selected_action' in extra:
        pre['selected_action'] = extra['selected_action']

    fixture = {key: copy.deepcopy(extra[key]) for key in
               ('schema_version', 'build', 'session_id', 'encounter_instance',
                'attack_id', 'rng_interval', 'observed') if key in extra}
    rec_id = extra.get('_rec_attack_id')
    if rec_id is not None:
        if extra.get('attack_id') != rec_id:
            raise ValueError('attack_id conflict or missing boundary identity')
        fixture['attack_id'] = rec_id
    fixture.update(pre_submit=pre, teacher_forced=extra.get('teacher_forced', False),
                   unsupported_state=list(dict.fromkeys(reasons)))
    return fixture


def assemble_captures_from_log(log_path, extra):
    """Read a log and join either one explicit boundary or {'boundaries': {id: extra}}.

    Errors and quarantines retain attack ID and raw parsed fields. 'valid' means
    structurally valid, not native parity: inspect eligibility before replay.
    """
    raw = Path(log_path).read_bytes()
    records = parse_sim_log(raw.decode('utf-8', errors='replace').splitlines())
    good, quarantined = partition_sim_log(records)
    result = {'valid': [], 'errors': [], 'quarantined': [],
              'source_sha256': hashlib.sha256(raw).hexdigest(), 'full_game_parity': False}
    for rec in quarantined:
        result['quarantined'].append({'attack_id': rec.attack_id,
                                      'reason': rec.quarantine_reason, 'raw': repr(rec)})
    for rec in good:
        evidence = {'attack_id': rec.attack_id,
                    'raw_fields': [{'key': list(k), 'value': v} for k, v in rec.fields.items()]}
        fixture = None
        try:
            if not isinstance(extra, dict):
                raise ValueError('sidecar must be an object')
            if 'boundaries' in extra:
                boundaries = extra['boundaries']
                if not isinstance(boundaries, dict):
                    raise ValueError('boundaries must be an object keyed by attack ID')
                boundary = boundaries.get(str(rec.attack_id))
            else:
                boundary = extra
            if not isinstance(boundary, dict) or boundary.get('attack_id') != rec.attack_id:
                raise ValueError('missing or conflicting sidecar for attack_id')
            fixture = assemble_encounter_from_fields(
                rec.fields, dict(boundary, _rec_attack_id=rec.attack_id))
            eligibility = validate_fixture(fixture)
            state_data = dict(fixture['pre_submit'])
            state_data.update({k: fixture[k] for k in ('build', 'session_id', 'encounter_instance')})
            state = build_encounter_state(state_data)
            reasons = list(dict.fromkeys(fixture['unsupported_state'] + state.unsupported_fields))
            result['valid'].append(dict(evidence, fixture=fixture,
                                        eligibility=eligibility.value, unsupported_fields=reasons))
        except (ValueError, TypeError, OverflowError) as exc:
            result['errors'].append(dict(evidence, fixture=None, eligibility='error',
                                         unsupported_fields=[str(exc)]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--boundaries', required=True, type=Path, help='Boundary-specific JSON sidecar')
    parser.add_argument('--output', required=True, type=Path, help='New report file')
    args = parser.parse_args()
    sidecar = args.boundaries.read_bytes()
    report = assemble_captures_from_log(args.log, json.loads(sidecar))
    report['sidecar_sha256'] = hashlib.sha256(sidecar).hexdigest()
    with args.output.open('x') as target:
        json.dump(report, target, indent=2, allow_nan=False)
        target.write('\n')
    print(f"{len(report['valid'])} validated, {len(report['errors'])} errors, "
          f"{len(report['quarantined'])} quarantined; native parity not established")
    return 1 if report['errors'] or report['quarantined'] or not report['valid'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
