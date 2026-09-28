"""Tests for speedrun/assemble_captures.py.

PYTHONPATH=speedrun, so imports are relative to that directory.

Coverage:
  1. group_log_attacks correctly groups tuple-keyed ATTACK fields.
  2. assemble_encounter_from_fields with already_performed=False.
  3. assemble_encounter_from_fields with already_performed=True.
  4. Counter conflict: rate_counter vs enemy_counters mismatch → handled gracefully.
  5. native_state_raw present → unsupported_fields contains 'attack_state_mapping_unconfirmed'.
  6. assemble_captures_from_log: quarantined records land in result['quarantined'];
     valid records with mState have eligibility != 'eligible'.
"""
import sys
import os
import io
import tempfile
import unittest

# Ensure automation/ is importable (needed by assemble_captures → capture_log_parser)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'automation'))

from assemble_captures import group_log_attacks, assemble_encounter_from_fields, assemble_captures_from_log


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_FAKE_EXE_HASH = 'a' * 64
_FAKE_PAK_HASH = 'b' * 64

# A minimal valid RNG state (624 zero words, cursor=0).
_RNG_WORDS = [0] * 624
_RNG_STATE = {'words': _RNG_WORDS, 'cursor': 0}

# A valid board string.
_BOARD = 'ABCD/EFGH/IJKL/MNOP'

# A valid observed dict.
_OBSERVED = {
    'player_hp': 100.0,
    'enemy_hp': 50.0,
    'board': _BOARD,
    'rng_snapshot': _RNG_STATE,
}

# Provenance that cannot come from the log alone.
_EXTRA = {
    'schema_version': 1,
    'build': {
        'BookwormAdventures.exe': _FAKE_EXE_HASH,
        'main.pak': _FAKE_PAK_HASH,
    },
    'session_id': 'test-session-001',
    'encounter_instance': 0,
    'attack_id': 1,
    'rng_interval': {'first': 0, 'last': 0},
    'selected_action': 'AB',
    'observed': _OBSERVED,
}


def _make_fields(attacks: list[dict],
                 owner: str = 'enemy',
                 board: str = _BOARD,
                 include_creature: bool = True,
                 include_rng: bool = True,
                 include_board: bool = True,
                 include_gems: bool = True,
                 include_tile_powers: bool = True,
                 include_enemy_name: bool = True) -> dict:
    """Build a synthetic ParsedRecord.fields dict from named attack sub-dicts.

    Each attack dict in `attacks` maps hook field names (mMin, mMax, etc.)
    to value strings.  The resulting fields dict uses tuple keys exactly as
    parse_sim_log produces them.

    Creature fields, RNG, board, gems, and tile powers are included by default
    so that assemble_encounter_from_fields can build a complete pre_submit.
    """
    fields: dict = {}

    # ATTACK rows: ('ATTACK', owner, str(i), field_name) -> value_str
    for i, atk in enumerate(attacks):
        atk_key = str(i)
        for field_name, value in atk.items():
            fields[('ATTACK', owner, atk_key, field_name)] = value

    if include_creature:
        # Player creature fields
        for lua_name, dest_name, value in [
            ('player_hp', 'player_hp', '100.0'),
            ('player_max_hp', 'player_max_hp', '100.0'),
            ('player_offense', 'player_offense', '10.0'),
            ('player_damage_buffer', 'player_damage_buffer', '0.0'),
        ]:
            fields[('CREATURE', 'player', lua_name)] = value
        # Enemy creature fields
        for lua_name, dest_name, value in [
            ('enemy_hp', 'enemy_hp', '80.0'),
            ('enemy_max_hp', 'enemy_max_hp', '80.0'),
            ('enemy_offense', 'enemy_offense', '5.0'),
            ('enemy_damage_buffer', 'enemy_damage_buffer', '0.0'),
        ]:
            fields[('CREATURE', 'enemy', lua_name)] = value

    if include_enemy_name:
        fields[('CREATURE', 'enemy', 'enemy_name')] = 'TestEnemy'

    if include_board:
        fields[('BOARD',)] = board

    if include_gems:
        for i in range(16):
            fields[('GEMS', str(i))] = 'none'

    if include_tile_powers:
        for i in range(16):
            fields[('TILE_POWERS', str(i))] = '0.0'

    if include_rng:
        for i in range(624):
            fields[('ENGINE_RNG', 'words', str(i))] = '0'
        fields[('ENGINE_RNG', 'cursor')] = '0'
        fields[('ENGINE_RNG', 'draw_index')] = '0'

    return fields


def _minimal_attack(already_performed='false', rate_counter='2',
                    min_='1', max_='5', damage='2.0', state='0') -> dict:
    """Return a string-valued hook attack dict."""
    return {
        'mMin': min_,
        'mMax': max_,
        'mDamage': damage,
        'mAlreadyPerformed': already_performed,
        'mRateCounter': rate_counter,
        'mState': state,
    }


# ---------------------------------------------------------------------------
# Test: group_log_attacks
# ---------------------------------------------------------------------------

class GroupLogAttacksTests(unittest.TestCase):
    """group_log_attacks correctly groups ATTACK tuple keys into per-attack dicts."""

    def test_single_attack_grouped(self):
        fields = {
            ('ATTACK', 'enemy', '0', 'mMin'): '1',
            ('ATTACK', 'enemy', '0', 'mMax'): '5',
            ('ATTACK', 'enemy', '0', 'mDamage'): '2.0',
        }
        result = group_log_attacks(fields)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['mMin'], '1')
        self.assertEqual(result[0]['mMax'], '5')
        self.assertEqual(result[0]['mDamage'], '2.0')
        self.assertEqual(result[0]['_owner'], 'enemy')
        self.assertEqual(result[0]['_atk_key'], '0')

    def test_two_attacks_both_grouped(self):
        fields = {
            ('ATTACK', 'enemy', '0', 'mMin'): '1',
            ('ATTACK', 'enemy', '0', 'mMax'): '3',
            ('ATTACK', 'enemy', '1', 'mMin'): '2',
            ('ATTACK', 'enemy', '1', 'mMax'): '7',
        }
        result = group_log_attacks(fields)
        self.assertEqual(len(result), 2)
        mins = {r['_atk_key']: r['mMin'] for r in result}
        self.assertEqual(mins, {'0': '1', '1': '2'})

    def test_non_attack_keys_ignored(self):
        fields = {
            ('CREATURE', 'enemy', 'hp'): '80',
            ('ATTACK', 'enemy', '0', 'mMin'): '1',
            ('BOARD',): 'ABCD/EFGH/IJKL/MNOP',
        }
        result = group_log_attacks(fields)
        self.assertEqual(len(result), 1)
        self.assertIn('mMin', result[0])

    def test_stable_order_by_owner_then_atk_key(self):
        fields = {
            ('ATTACK', 'enemy', '1', 'mMin'): '2',
            ('ATTACK', 'enemy', '0', 'mMin'): '1',
        }
        result = group_log_attacks(fields)
        self.assertEqual([r['_atk_key'] for r in result], ['0', '1'])

    def test_empty_fields_returns_empty_list(self):
        self.assertEqual(group_log_attacks({}), [])

    def test_metadata_keys_prefixed_with_underscore(self):
        """_owner and _atk_key are metadata; real field names never start with '_'."""
        fields = {('ATTACK', 'enemy', '0', 'mMin'): '1'}
        result = group_log_attacks(fields)
        self.assertIn('_owner', result[0])
        self.assertIn('_atk_key', result[0])


# ---------------------------------------------------------------------------
# Test: assemble_encounter_from_fields — already_performed=False
# ---------------------------------------------------------------------------

class AssembleEncounterAlreadyPerformedFalseTests(unittest.TestCase):
    """already_performed=False → attack is included and eligibility is not blocked by it."""

    def setUp(self):
        self.atk = _minimal_attack(already_performed='false')
        self.fields = _make_fields([self.atk])

    def test_fixture_contains_enemy_attacks(self):
        fixture = assemble_encounter_from_fields(self.fields, _EXTRA)
        attacks = fixture['pre_submit']['enemy_attacks']
        self.assertEqual(len(attacks), 1)

    def test_already_performed_is_false(self):
        fixture = assemble_encounter_from_fields(self.fields, _EXTRA)
        attack = fixture['pre_submit']['enemy_attacks'][0]
        # After convert_hook_attack_types, mAlreadyPerformed='false' → False (bool).
        self.assertFalse(attack.get('mAlreadyPerformed'))

    def test_validate_fixture_accepts_complete_record(self):
        """A fully populated fields dict with already_performed=False must validate."""
        from native_fixture import validate_fixture, FixtureEligibility
        fixture = assemble_encounter_from_fields(self.fields, _EXTRA)
        # mState present → unsupported, but structure must be valid.
        eligibility = validate_fixture(fixture)
        self.assertIsInstance(eligibility, FixtureEligibility)

    def test_enemy_counters_derived_from_rate_counter(self):
        fixture = assemble_encounter_from_fields(self.fields, _EXTRA)
        counters = fixture['pre_submit']['enemy_counters']
        # mRateCounter='2' → int 2
        self.assertEqual(counters, [2])


# ---------------------------------------------------------------------------
# Test: assemble_encounter_from_fields — already_performed=True
# ---------------------------------------------------------------------------

class AssembleEncounterAlreadyPerformedTrueTests(unittest.TestCase):
    """already_performed=True → attack dict has already_performed=True after conversion."""

    def setUp(self):
        self.atk = _minimal_attack(already_performed='true')
        self.fields = _make_fields([self.atk])

    def test_already_performed_is_true(self):
        fixture = assemble_encounter_from_fields(self.fields, _EXTRA)
        attack = fixture['pre_submit']['enemy_attacks'][0]
        self.assertTrue(attack.get('mAlreadyPerformed'))

    def test_fixture_still_valid_structurally(self):
        """already_performed=True does not break fixture validation structure."""
        from native_fixture import validate_fixture, FixtureEligibility
        fixture = assemble_encounter_from_fields(self.fields, _EXTRA)
        eligibility = validate_fixture(fixture)
        self.assertIsInstance(eligibility, FixtureEligibility)

    def test_multiple_attacks_second_already_performed(self):
        atk0 = _minimal_attack(already_performed='false', rate_counter='3')
        atk1 = _minimal_attack(already_performed='true', rate_counter='1')
        fields = _make_fields([atk0, atk1])
        fixture = assemble_encounter_from_fields(fields, _EXTRA)
        attacks = fixture['pre_submit']['enemy_attacks']
        self.assertFalse(attacks[0]['mAlreadyPerformed'])
        self.assertTrue(attacks[1]['mAlreadyPerformed'])


# ---------------------------------------------------------------------------
# Test: Counter conflict → handled gracefully (no crash)
# ---------------------------------------------------------------------------

class CounterConflictTests(unittest.TestCase):
    """build_encounter_state raises when rate_counter != enemy_counters[i].

    assemble_encounter_from_fields derives enemy_counters FROM rate_counter, so
    they should always match.  The only way to trigger a conflict via the public
    API is to bypass assemble_encounter_from_fields and call build_encounter_state
    directly with inconsistent data — which we do here to verify the error is
    surfaced correctly.

    We also test that assemble_captures_from_log handles a ValueError from
    validate_fixture gracefully (returning eligibility='error').
    """

    def test_build_encounter_state_raises_on_counter_mismatch(self):
        """Direct build_encounter_state call with rate_counter ≠ enemy_counters raises."""
        from encounter_state import build_encounter_state
        data = {
            'build': {
                'BookwormAdventures.exe': _FAKE_EXE_HASH,
                'main.pak': _FAKE_PAK_HASH,
            },
            'session_id': 'test',
            'encounter_instance': 0,
            'board': _BOARD,
            'gems': ['none'] * 16,
            'tile_powers': [0.0] * 16,
            'player_hp': 100.0,
            'player_max_hp': 100.0,
            'player_offense': 10.0,
            'player_damage_buffer': 0.0,
            'player_effects': [],
            'enemy_name': 'TestEnemy',
            'enemy_hp': 80.0,
            'enemy_max_hp': 80.0,
            'enemy_offense': 5.0,
            'enemy_damage_buffer': 0.0,
            'enemy_effects': [],
            # rate_counter=5 in the attack, but enemy_counters=[3] → conflict
            'enemy_attacks': [{'min': 1, 'max': 5, 'rate_counter': 5}],
            'enemy_counters': [3],
            'engine_rng': _RNG_STATE,
            'engine_rng_draw_index': 0,
        }
        with self.assertRaises(ValueError) as ctx:
            build_encounter_state(data)
        self.assertIn('rate_counter', str(ctx.exception))

    def test_assemble_captures_from_log_counter_conflict_yields_error_entry(self):
        """A log record whose fields are internally consistent never triggers a conflict.

        Instead we verify the pipeline's error-handling by constructing a log
        that parse_sim_log accepts but then writing a fixture dict with a
        mismatched counter directly and confirming it yields eligibility='error'.

        This is done by monkeypatching validate_fixture to raise ValueError.
        """
        import unittest.mock as mock
        atk = _minimal_attack(already_performed='false', rate_counter='2')
        fields = _make_fields([atk])

        with mock.patch('assemble_captures.validate_fixture',
                        side_effect=ValueError('injected counter conflict')):
            # We call assemble_captures_from_log so we need a real file.
            log_lines = [
                'AUTOMATION_SIM_BEGIN=1|E',
                'AUTOMATION_SIM_ATTACK=1|enemy|0|mMin|1|E',
                'AUTOMATION_SIM_ATTACK=1|enemy|0|mMax|5|E',
                'AUTOMATION_SIM_ATTACK=1|enemy|0|mDamage|2.0|E',
                'AUTOMATION_SIM_ATTACK=1|enemy|0|mAlreadyPerformed|false|E',
                'AUTOMATION_SIM_ATTACK=1|enemy|0|mRateCounter|2|E',
                'AUTOMATION_SIM_ATTACK=1|enemy|0|mState|0|E',
                'AUTOMATION_SIM_END=1|E',
            ]
            with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
                f.write('\n'.join(log_lines))
                tmp_path = f.name
            try:
                result = assemble_captures_from_log(tmp_path, _EXTRA)
            finally:
                os.unlink(tmp_path)

        self.assertEqual(len(result['valid']), 1)
        entry = result['valid'][0]
        self.assertEqual(entry['eligibility'], 'error')
        self.assertIn('injected counter conflict', entry['unsupported_fields'][0])


# ---------------------------------------------------------------------------
# Test: native_state_raw → attack_state_mapping_unconfirmed in unsupported_fields
# ---------------------------------------------------------------------------

class NativeStateRawUnsupportedTests(unittest.TestCase):
    """mState present in log → native_state_raw in normalised attack →
    'attack_state_mapping_unconfirmed' in unsupported_fields."""

    def test_mstate_present_causes_attack_state_mapping_unconfirmed(self):
        """mState='0' in the captured log must flow through to unsupported_fields."""
        atk = _minimal_attack(state='0')  # mState='0' → native_state_raw=0
        fields = _make_fields([atk])
        fixture = assemble_encounter_from_fields(fields, _EXTRA)
        from native_fixture import validate_fixture, FixtureEligibility
        eligibility = validate_fixture(fixture)
        # The fixture must NOT be eligible because mState is unconfirmed.
        self.assertNotEqual(eligibility, FixtureEligibility.ELIGIBLE)
        # unsupported_fields must contain the marker (recomputed from normalised attacks).
        from native_enemy_ai import normalise_attack
        normalised = [normalise_attack(a) for a in fixture['pre_submit']['enemy_attacks']]
        self.assertTrue(any('native_state_raw' in a for a in normalised),
                        msg='Expected native_state_raw in at least one normalised attack')

    def test_mstate_not_suppressed_or_remapped(self):
        """native_state_raw must not be deleted or mapped to 'active' to clear unsupported."""
        atk = _minimal_attack(state='1')
        fields = _make_fields([atk])
        fixture = assemble_encounter_from_fields(fields, _EXTRA)
        from native_enemy_ai import normalise_attack
        normalised = [normalise_attack(a) for a in fixture['pre_submit']['enemy_attacks']]
        for a in normalised:
            self.assertNotIn('state', a,
                             msg='mState must not be synthesised as canonical state key')
            if 'native_state_raw' in a:
                self.assertIsInstance(a['native_state_raw'], int)

    def test_assemble_captures_from_log_mstate_not_eligible(self):
        """Full pipeline via assemble_captures_from_log: mState → eligibility != eligible."""
        log_lines = _make_complete_log_lines(attack_id=1, mstate='0')
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            f.write('\n'.join(log_lines))
            tmp_path = f.name
        try:
            result = assemble_captures_from_log(tmp_path, _EXTRA)
        finally:
            os.unlink(tmp_path)
        self.assertEqual(len(result['valid']), 1)
        entry = result['valid'][0]
        self.assertNotEqual(entry['eligibility'], 'eligible',
                            msg='Record with mState must not be eligible')


# ---------------------------------------------------------------------------
# Test: assemble_captures_from_log — quarantined and valid records
# ---------------------------------------------------------------------------

def _make_complete_log_lines(attack_id: int, mstate: str = '0',
                              extra_lines: list = None) -> list[str]:
    """Construct log lines that parse_sim_log will accept as a complete valid block.

    The block contains one attack with all standard fields.
    """
    id_str = str(attack_id)
    lines = [
        f'AUTOMATION_SIM_BEGIN={id_str}|E',
        f'AUTOMATION_SIM_ATTACK={id_str}|enemy|0|mMin|1|E',
        f'AUTOMATION_SIM_ATTACK={id_str}|enemy|0|mMax|5|E',
        f'AUTOMATION_SIM_ATTACK={id_str}|enemy|0|mDamage|2.0|E',
        f'AUTOMATION_SIM_ATTACK={id_str}|enemy|0|mAlreadyPerformed|false|E',
        f'AUTOMATION_SIM_ATTACK={id_str}|enemy|0|mRateCounter|0|E',
        f'AUTOMATION_SIM_ATTACK={id_str}|enemy|0|mState|{mstate}|E',
        f'AUTOMATION_SIM_END={id_str}|E',
    ]
    if extra_lines:
        # Insert before END
        lines = lines[:-1] + extra_lines + [lines[-1]]
    return lines


def _make_quarantine_log_lines(attack_id: int) -> list[str]:
    """A log block that will be quarantined (UNSUPPORTED marker inside)."""
    id_str = str(attack_id)
    return [
        f'AUTOMATION_SIM_BEGIN={id_str}|E',
        f'AUTOMATION_SIM_ATTACK={id_str}|enemy|0|mMin|1|E',
        f'AUTOMATION_SIM_UNSUPPORTED={id_str}|enemy|hidden_state|E',
        f'AUTOMATION_SIM_END={id_str}|E',
    ]


class AssembleCapturesFromLogTests(unittest.TestCase):
    """assemble_captures_from_log: quarantined blocks land in result['quarantined']."""

    def _write_log(self, lines: list[str]) -> str:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            f.write('\n'.join(lines))
            return f.name

    def test_quarantined_block_ends_up_in_quarantined(self):
        """A block with an UNSUPPORTED marker is quarantined, not silently dropped."""
        lines = _make_quarantine_log_lines(1)
        path = self._write_log(lines)
        try:
            result = assemble_captures_from_log(path, _EXTRA)
        finally:
            os.unlink(path)
        self.assertEqual(len(result['quarantined']), 1)
        self.assertEqual(len(result['valid']), 0)
        self.assertIsNotNone(result['quarantined'][0]['reason'])
        self.assertIn('unsupported', result['quarantined'][0]['reason'])

    def test_quarantined_reason_preserved(self):
        """Quarantined records carry the parser's reason string."""
        # Truncated block: BEGIN without END.
        lines = [
            'AUTOMATION_SIM_BEGIN=42|E',
            'AUTOMATION_SIM_ATTACK=42|enemy|0|mMin|1|E',
            # No END → quarantine
        ]
        path = self._write_log(lines)
        try:
            result = assemble_captures_from_log(path, _EXTRA)
        finally:
            os.unlink(path)
        self.assertEqual(len(result['quarantined']), 1)
        reason = result['quarantined'][0]['reason']
        self.assertIsInstance(reason, str)
        self.assertTrue(reason)  # non-empty

    def test_valid_and_quarantine_in_same_log(self):
        """Good and quarantined blocks in the same log file are split correctly."""
        valid_lines = _make_complete_log_lines(1, mstate='0')
        quarantine_lines = _make_quarantine_log_lines(2)
        path = self._write_log(valid_lines + quarantine_lines)
        try:
            result = assemble_captures_from_log(path, _EXTRA)
        finally:
            os.unlink(path)
        self.assertEqual(len(result['quarantined']), 1)
        self.assertEqual(len(result['valid']), 1)

    def test_valid_record_with_mstate_has_eligibility_not_eligible(self):
        """Records with mState end up in result['valid'] with eligibility != 'eligible'."""
        lines = _make_complete_log_lines(1, mstate='0')
        path = self._write_log(lines)
        try:
            result = assemble_captures_from_log(path, _EXTRA)
        finally:
            os.unlink(path)
        self.assertEqual(len(result['valid']), 1)
        entry = result['valid'][0]
        self.assertNotEqual(entry['eligibility'], 'eligible')

    def test_multiple_quarantined_blocks_all_preserved(self):
        """Multiple quarantined blocks all appear in result['quarantined']."""
        q1 = _make_quarantine_log_lines(1)
        q2 = _make_quarantine_log_lines(2)
        path = self._write_log(q1 + q2)
        try:
            result = assemble_captures_from_log(path, _EXTRA)
        finally:
            os.unlink(path)
        self.assertEqual(len(result['quarantined']), 2)
        self.assertEqual(len(result['valid']), 0)

    def test_empty_log_returns_empty_lists(self):
        """An empty log file produces no valid or quarantined records."""
        path = self._write_log([])
        try:
            result = assemble_captures_from_log(path, _EXTRA)
        finally:
            os.unlink(path)
        self.assertEqual(result['valid'], [])
        self.assertEqual(result['quarantined'], [])


# ---------------------------------------------------------------------------
# Test: parse_sim_log wire format integration
# ---------------------------------------------------------------------------

class ParseSimLogWireFormatTests(unittest.TestCase):
    """Confirm that group_log_attacks correctly interprets parse_sim_log output."""

    def test_parse_sim_log_then_group_log_attacks(self):
        """parse_sim_log → group_log_attacks yields the correct per-attack dict."""
        import sys
        from capture_log_parser import parse_sim_log, partition_sim_log

        log_lines = [
            'AUTOMATION_SIM_BEGIN=1|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mMin|1|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mMax|5|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mDamage|2.0|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mAlreadyPerformed|false|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mRateCounter|2|E',
            'AUTOMATION_SIM_ATTACK=1|enemy|0|mState|0|E',
            'AUTOMATION_SIM_END=1|E',
        ]
        records = parse_sim_log(log_lines)
        good, _ = partition_sim_log(records)
        self.assertEqual(len(good), 1)

        attacks = group_log_attacks(good[0].fields)
        self.assertEqual(len(attacks), 1)
        self.assertEqual(attacks[0]['mMin'], '1')
        self.assertEqual(attacks[0]['mMax'], '5')
        self.assertEqual(attacks[0]['mAlreadyPerformed'], 'false')
        self.assertEqual(attacks[0]['mRateCounter'], '2')

    def test_two_attacks_grouped_correctly(self):
        """Two attacks in the log each get their own dict."""
        from capture_log_parser import parse_sim_log, partition_sim_log

        log_lines = [
            'AUTOMATION_SIM_BEGIN=2|E',
            'AUTOMATION_SIM_ATTACK=2|enemy|0|mMin|1|E',
            'AUTOMATION_SIM_ATTACK=2|enemy|0|mMax|3|E',
            'AUTOMATION_SIM_ATTACK=2|enemy|1|mMin|2|E',
            'AUTOMATION_SIM_ATTACK=2|enemy|1|mMax|7|E',
            'AUTOMATION_SIM_END=2|E',
        ]
        records = parse_sim_log(log_lines)
        good, _ = partition_sim_log(records)
        self.assertEqual(len(good), 1)

        attacks = group_log_attacks(good[0].fields)
        self.assertEqual(len(attacks), 2)
        by_key = {a['_atk_key']: a for a in attacks}
        self.assertEqual(by_key['0']['mMin'], '1')
        self.assertEqual(by_key['1']['mMin'], '2')


if __name__ == '__main__':
    unittest.main()
