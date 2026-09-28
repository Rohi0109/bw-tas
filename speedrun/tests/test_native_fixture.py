import unittest

from native_fixture import (
    SCHEMA_VERSION,
    FixtureEligibility,
    validate_fixture,
    validate_build_identity,
)

_VALID_HASH = 'a' * 64
_OTHER_HASH = 'b' * 64


def _minimal_fixture(**overrides) -> dict:
    base = {
        'schema_version': SCHEMA_VERSION,
        'build': {
            'BookwormAdventures.exe': _VALID_HASH,
            'main.pak': _OTHER_HASH,
        },
        'session_id': 'sess-001',
        'encounter_instance': 0,
        'attack_id': 1,
        'rng_interval': {'first': 10, 'last': 15},
        'pre_submit': {
            'board': 'ABCD/EFGH/IJKL/MNOP',
            'gems': ['none'] * 16,
            'tile_powers': [0.0] * 16,
            'player_hp': 10.0,
            'player_max_hp': 100.0,
            'player_offense': 1.0,
            'player_damage_buffer': 0.0,
            'player_effects': [],
            'enemy_name': 'TestEnemy',
            'enemy_hp': 5.0,
            'enemy_max_hp': 50.0,
            'enemy_offense': 1.0,
            'enemy_damage_buffer': 0.0,
            'enemy_effects': [],
            'enemy_attacks': [],
            'enemy_counters': [],
            'engine_rng': {'words': [0] * 624, 'cursor': 0},
            'engine_rng_draw_index': 10,
            'selected_action': 'ABCD',  # A B C D all on board
        },
        'observed': {
            'player_hp': 9.0,
            'enemy_hp': 0.0,
            'board': 'EFGH/IJKL/MNOP/ABCD',  # post-turn board (same letters, rotated)
            'rng_snapshot': {'words': [0] * 624, 'cursor': 4},
        },
        'unsupported_state': [],
        'teacher_forced': False,
    }
    base.update(overrides)
    return base


def _min_pre_submit(**overrides) -> dict:
    """Return a valid pre_submit dict with specific field overrides."""
    ps = dict(_minimal_fixture()['pre_submit'])
    ps.update(overrides)
    return ps


class ValidateFixtureTests(unittest.TestCase):

    def test_valid_minimal_is_eligible(self):
        self.assertEqual(validate_fixture(_minimal_fixture()), FixtureEligibility.ELIGIBLE)

    def test_unsupported_state_returns_unsupported(self):
        f = _minimal_fixture(unsupported_state=['effect-queue'])
        self.assertEqual(validate_fixture(f), FixtureEligibility.UNSUPPORTED_STATE)

    def test_teacher_forced_returns_teacher_forced(self):
        f = _minimal_fixture(teacher_forced=True)
        self.assertEqual(validate_fixture(f), FixtureEligibility.TEACHER_FORCED)

    def test_teacher_forced_overrides_unsupported_state(self):
        # teacher_forced is checked first
        f = _minimal_fixture(teacher_forced=True, unsupported_state=['x'])
        self.assertEqual(validate_fixture(f), FixtureEligibility.TEACHER_FORCED)

    def test_optional_prediction_accepted(self):
        f = _minimal_fixture(prediction={'word': 'TEST', 'damage': 5})
        self.assertEqual(validate_fixture(f), FixtureEligibility.ELIGIBLE)

    def test_prediction_not_a_dict_raises(self):
        f = _minimal_fixture(prediction='bad')
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_missing_required_field_raises(self):
        for field in ('schema_version', 'build', 'session_id', 'encounter_instance',
                      'attack_id', 'rng_interval', 'pre_submit', 'observed',
                      'unsupported_state', 'teacher_forced'):
            with self.subTest(field=field):
                f = _minimal_fixture()
                del f[field]
                with self.assertRaises(ValueError):
                    validate_fixture(f)

    def test_unknown_field_raises(self):
        f = _minimal_fixture(extra_unknown_field=True)
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_wrong_schema_version_raises(self):
        f = _minimal_fixture(schema_version=99)
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_rng_interval_first_greater_than_last_raises(self):
        f = _minimal_fixture(rng_interval={'first': 20, 'last': 10})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_rng_interval_equal_first_last_ok(self):
        f = _minimal_fixture(rng_interval={'first': 5, 'last': 5})
        self.assertEqual(validate_fixture(f), FixtureEligibility.ELIGIBLE)

    def test_rng_interval_missing_key_raises(self):
        f = _minimal_fixture(rng_interval={'first': 5})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_rng_interval_negative_raises(self):
        f = _minimal_fixture(rng_interval={'first': -1, 'last': 5})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_build_missing_key_raises(self):
        f = _minimal_fixture(build={'BookwormAdventures.exe': _VALID_HASH})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_build_wrong_length_raises(self):
        f = _minimal_fixture(build={'BookwormAdventures.exe': 'abc', 'main.pak': _OTHER_HASH})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_session_id_empty_raises(self):
        f = _minimal_fixture(session_id='')
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_encounter_instance_negative_raises(self):
        f = _minimal_fixture(encounter_instance=-1)
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_teacher_forced_not_bool_raises(self):
        f = _minimal_fixture(teacher_forced=1)
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_unsupported_state_not_list_raises(self):
        f = _minimal_fixture(unsupported_state='x')
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_empty_pre_submit_raises(self):
        f = _minimal_fixture(pre_submit={})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_empty_observed_raises(self):
        f = _minimal_fixture(observed={})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_missing_player_hp_raises(self):
        f = _minimal_fixture(pre_submit={'enemy_hp': 5})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_missing_enemy_hp_raises(self):
        f = _minimal_fixture(pre_submit={'player_hp': 10})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_non_numeric_hp_raises(self):
        f = _minimal_fixture(pre_submit={'player_hp': 'ten', 'enemy_hp': 5})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_observed_missing_field_raises(self):
        # HP-only observed is insufficient for full-turn parity.
        f = _minimal_fixture(observed={'player_hp': 9})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_nan_hp_raises(self):
        f = _minimal_fixture(pre_submit=_min_pre_submit(player_hp=float('nan')))
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_negative_hp_raises(self):
        f = _minimal_fixture(pre_submit=_min_pre_submit(enemy_hp=-1))
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_missing_board_raises(self):
        ps = _min_pre_submit()
        del ps['board']
        f = _minimal_fixture(pre_submit=ps)
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_missing_rng_snapshot_raises(self):
        ps = _min_pre_submit()
        del ps['engine_rng']
        f = _minimal_fixture(pre_submit=ps)
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_observed_non_numeric_hp_raises(self):
        f = _minimal_fixture(observed={'player_hp': 'nine', 'enemy_hp': 0,
                                        'board': 'EFGH/IJKL/MNOP/ABCD',
                                        'rng_snapshot': {'words': [0]*624, 'cursor': 4}})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_observed_none_hp_raises(self):
        f = _minimal_fixture(observed={'player_hp': None, 'enemy_hp': 0,
                                        'board': 'EFGH/IJKL/MNOP/ABCD',
                                        'rng_snapshot': {'words': [0]*624, 'cursor': 4}})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_observed_negative_hp_raises(self):
        f = _minimal_fixture(observed={'player_hp': -1, 'enemy_hp': 0,
                                        'board': 'EFGH/IJKL/MNOP/ABCD',
                                        'rng_snapshot': {'words': [0]*624, 'cursor': 4}})
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_board_not_string_raises(self):
        f = _minimal_fixture(pre_submit=_min_pre_submit(board=[None]))
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_board_wrong_format_raises(self):
        f = _minimal_fixture(pre_submit=_min_pre_submit(board='not_a_board'))
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_action_with_underscore_raises(self):
        f = _minimal_fixture(pre_submit=_min_pre_submit(selected_action='NOT_A_WORD'))
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_rng_empty_words_raises(self):
        f = _minimal_fixture(pre_submit=_min_pre_submit(engine_rng={'words': [], 'cursor': 0}))
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_rng_negative_cursor_raises(self):
        f = _minimal_fixture(pre_submit=_min_pre_submit(engine_rng={'words': [0]*624, 'cursor': -999}))
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_pre_submit_rng_out_of_range_word_raises(self):
        f = _minimal_fixture(pre_submit=_min_pre_submit(engine_rng={'words': [-1]+[0]*623, 'cursor': 0}))
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_action_not_on_board_raises(self):
        # T and S are not on ABCD/EFGH/IJKL/MNOP.
        f = _minimal_fixture(pre_submit=_min_pre_submit(selected_action='TEST'))
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_action_too_long_raises(self):
        # 17 letters exceeds the 16-tile board.
        f = _minimal_fixture(pre_submit=_min_pre_submit(selected_action='A' * 17))
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_observed_missing_board_raises(self):
        obs = {'player_hp': 9.0, 'enemy_hp': 0.0, 'rng_snapshot': {'words': [0]*624, 'cursor': 4}}
        f = _minimal_fixture(observed=obs)
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_observed_missing_rng_raises(self):
        obs = {'player_hp': 9.0, 'enemy_hp': 0.0, 'board': 'EFGH/IJKL/MNOP/ABCD'}
        f = _minimal_fixture(observed=obs)
        with self.assertRaises(ValueError):
            validate_fixture(f)

    def test_unsupported_derived_from_encounter_gems(self):
        # Non-plain gems in pre_submit must trigger UNSUPPORTED_STATE
        # even when unsupported_state=[] (derived from encounter, not caller-trusted).
        ps = _min_pre_submit(gems=['diamond'] + ['none'] * 15)
        f = _minimal_fixture(pre_submit=ps, unsupported_state=[])
        self.assertEqual(validate_fixture(f), FixtureEligibility.UNSUPPORTED_STATE)

    def test_hp_only_observed_raises(self):
        # HP-only observed is not sufficient for full-turn parity.
        f = _minimal_fixture(observed={'player_hp': 9.0, 'enemy_hp': 0.0})
        with self.assertRaises(ValueError):
            validate_fixture(f)


class ValidateBuildIdentityTests(unittest.TestCase):

    def test_matching_hashes_no_raise(self):
        f = _minimal_fixture()
        validate_build_identity(f, _VALID_HASH, _OTHER_HASH)

    def test_exe_mismatch_raises(self):
        f = _minimal_fixture()
        with self.assertRaises(ValueError):
            validate_build_identity(f, 'c' * 64, _OTHER_HASH)

    def test_pak_mismatch_raises(self):
        f = _minimal_fixture()
        with self.assertRaises(ValueError):
            validate_build_identity(f, _VALID_HASH, 'c' * 64)

    def test_both_mismatch_raises(self):
        f = _minimal_fixture()
        with self.assertRaises(ValueError):
            validate_build_identity(f, 'c' * 64, 'c' * 64)


if __name__ == '__main__':
    unittest.main()
