import unittest

from encounter_state import (
    ENCOUNTER_STATE_VERSION,
    EncounterEligibility,
    build_encounter_state,
    deserialise,
    encounter_eligibility,
    serialise,
)


_RNG = {'words': [0] * 624, 'cursor': 0}
_BUILD = {
    'BookwormAdventures.exe': 'a' * 64,
    'main.pak': 'b' * 64,
}


def _plain_data(**overrides):
    data = {
        'build': _BUILD,
        'session_id': 'test-session-1',
        'encounter_instance': 0,
        'board': 'ABCD/EFGH/IJKL/MNOP',
        'gems': ['none'] * 16,
        'tile_powers': [0.0] * 16,
        'player_hp': 10.0,
        'player_max_hp': 10.0,
        'player_offense': 0.0,
        'player_damage_buffer': 0.0,
        'player_effects': [],
        'enemy_name': 'Trojan Spearman',
        'enemy_hp': 8.0,
        'enemy_max_hp': 8.0,
        'enemy_offense': 0.0,
        'enemy_damage_buffer': 0.0,
        'enemy_effects': [],
        'enemy_attacks': [{'mMin': 2, 'mMax': 5, 'mRateCounter': 0, 'mAlreadyPerformed': False, 'mDamage': 1.0, 'mState': 0}],
        'enemy_counters': [0],
        'engine_rng': _RNG,
        'engine_rng_draw_index': 0,
    }
    data.update(overrides)
    return data


class EligibilityTests(unittest.TestCase):
    def test_plain_encounter_with_mstate_is_unsupported(self):
        # mState is always present in hook attacks; its integer→string mapping is
        # unconfirmed, so attack_state_mapping_unconfirmed is added automatically.
        state = build_encounter_state(_plain_data())
        self.assertIn('attack_state_mapping_unconfirmed', state.unsupported_fields)
        self.assertEqual(encounter_eligibility(state), EncounterEligibility.UNSUPPORTED)

    def test_non_none_gem_is_unsupported(self):
        gems = ['none'] * 16
        gems[3] = 'ruby'
        state = build_encounter_state(_plain_data(gems=gems))
        self.assertEqual(encounter_eligibility(state), EncounterEligibility.UNSUPPORTED)
        self.assertIn('gems', state.unsupported_fields)

    def test_all_gem_types_trigger_unsupported(self):
        for gem in ('ruby', 'emerald', 'sapphire', 'diamond'):
            gems = ['none'] * 16
            gems[0] = gem
            state = build_encounter_state(_plain_data(gems=gems))
            self.assertIn('gems', state.unsupported_fields)

    def test_non_empty_player_effects_unsupported(self):
        effects = [{'kind': 'poison', 'turns': 2, 'value': 1.0}]
        state = build_encounter_state(_plain_data(player_effects=effects))
        self.assertIn('player_effects', state.unsupported_fields)

    def test_non_empty_enemy_effects_unsupported(self):
        effects = [{'kind': 'regen', 'turns': 1, 'value': 0.5}]
        state = build_encounter_state(_plain_data(enemy_effects=effects))
        self.assertIn('enemy_effects', state.unsupported_fields)

    def test_qrand_state_non_none_is_unsupported(self):
        state = build_encounter_state(_plain_data(qrand_state={'some': 'state'}))
        self.assertIn('qrand_state', state.unsupported_fields)

    def test_non_zero_tile_power_is_unsupported(self):
        powers = [0.0] * 16
        powers[0] = 1.5
        state = build_encounter_state(_plain_data(tile_powers=powers))
        self.assertIn('tile_powers', state.unsupported_fields)

    def test_multiple_unsupported_fields_all_recorded(self):
        gems = ['none'] * 15 + ['ruby']
        effects = [{'k': 'v'}]
        state = build_encounter_state(_plain_data(gems=gems, player_effects=effects,
                                                  qrand_state='x'))
        for field in ('gems', 'player_effects', 'qrand_state'):
            self.assertIn(field, state.unsupported_fields)


    def test_native_state_raw_marks_unsupported(self):
        # mState is always present in hook attacks
        state = build_encounter_state(_plain_data())
        self.assertIn('attack_state_mapping_unconfirmed', state.unsupported_fields)

    def test_extreme_mstate_not_eligible(self):
        data = _plain_data()
        data['enemy_attacks'][0]['mState'] = 999
        state = build_encounter_state(data)
        elig = encounter_eligibility(state)
        # unsupported state → not ELIGIBLE
        self.assertNotEqual(elig.value, 'eligible')

    def test_rate_counter_conflict_rejected(self):
        data = _plain_data()
        data['enemy_attacks'][0]['mRateCounter'] = 99  # conflicts with enemy_counters[0]=0
        with self.assertRaises(ValueError):
            build_encounter_state(data)


class SerialiseRoundtripTests(unittest.TestCase):
    def test_plain_state_round_trips(self):
        original = build_encounter_state(_plain_data())
        restored = deserialise(serialise(original))
        self.assertEqual(serialise(original), serialise(restored))

    def test_unsupported_state_round_trips(self):
        gems = ['none'] * 16
        gems[1] = 'emerald'
        original = build_encounter_state(_plain_data(gems=gems))
        restored = deserialise(serialise(original))
        self.assertIn('gems', restored.unsupported_fields)
        self.assertEqual(serialise(original), serialise(restored))

    def test_schema_version_preserved(self):
        state = build_encounter_state(_plain_data())
        self.assertEqual(serialise(state)['schema_version'], ENCOUNTER_STATE_VERSION)

    def test_wrong_schema_version_raises(self):
        data = serialise(build_encounter_state(_plain_data()))
        data['schema_version'] = 999
        with self.assertRaises(ValueError):
            deserialise(data)


class ValidationTests(unittest.TestCase):
    def test_missing_required_field_raises(self):
        for field in ('build', 'session_id', 'board', 'gems', 'tile_powers',
                      'player_hp', 'player_max_hp', 'enemy_name', 'enemy_hp',
                      'enemy_max_hp', 'engine_rng', 'engine_rng_draw_index'):
            data = _plain_data()
            del data[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_encounter_state(data)

    def test_bad_board_format_raises(self):
        for bad in ('', 'abcd/efgh/ijkl/mnop', 'ABCDE/FGHI/JKLM/NOPQ',
                    'ABCD/EFGH/IJKL', 'ABCD-EFGH-IJKL-MNOP'):
            with self.subTest(board=bad), self.assertRaises(ValueError):
                build_encounter_state(_plain_data(board=bad))

    def test_engine_rng_cursor_out_of_range_raises(self):
        for bad_cursor in (-1, 625, 1000):
            rng = {'words': [0] * 624, 'cursor': bad_cursor}
            with self.subTest(cursor=bad_cursor), self.assertRaises(ValueError):
                build_encounter_state(_plain_data(engine_rng=rng))

    def test_engine_rng_wrong_word_count_raises(self):
        rng = {'words': [0] * 100, 'cursor': 0}
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(engine_rng=rng))

    def test_player_hp_exceeds_max_raises(self):
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(player_hp=20.0, player_max_hp=10.0))

    def test_enemy_hp_exceeds_max_raises(self):
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(enemy_hp=99.0, enemy_max_hp=8.0))

    def test_empty_session_id_raises(self):
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(session_id=''))

    def test_bad_build_hash_raises(self):
        bad_build = {'BookwormAdventures.exe': 'not-a-hash', 'main.pak': 'b' * 64}
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(build=bad_build))

    def test_gems_wrong_count_raises(self):
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(gems=['none'] * 15))

    def test_tile_powers_wrong_count_raises(self):
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(tile_powers=[0.0] * 4))

    def test_negative_hp_raises(self):
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(player_hp=-1.0))

    def test_nan_hp_raises(self):
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(enemy_hp=float('nan')))

    def test_negative_enemy_counter_raises(self):
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(enemy_counters=[-1]))

    def test_encounter_instance_negative_raises(self):
        with self.assertRaises(ValueError):
            build_encounter_state(_plain_data(encounter_instance=-1))

    def test_attack_counter_length_mismatch_raises(self):
        # enemy_attacks and enemy_counters must have equal length.
        data = _plain_data()
        data['enemy_attacks'] = []
        data['enemy_counters'] = [1]
        with self.assertRaises(ValueError):
            build_encounter_state(data)

    def test_attack_entry_missing_min_raises(self):
        data = _plain_data()
        data['enemy_attacks'] = [{'max': 5}]
        data['enemy_counters'] = [0]
        with self.assertRaises(ValueError):
            build_encounter_state(data)

    def test_attack_entry_not_dict_raises(self):
        data = _plain_data()
        data['enemy_attacks'] = ['not-a-dict']
        data['enemy_counters'] = [0]
        with self.assertRaises(ValueError):
            build_encounter_state(data)


class AttackNormalisationTests(unittest.TestCase):
    def test_m_prefixed_attacks_normalised_to_canonical(self):
        data = _plain_data()
        state = build_encounter_state(data)
        attack = state.enemy_attacks[0]
        self.assertIn('min', attack)
        self.assertIn('max', attack)
        self.assertIn('already_performed', attack)
        self.assertIn('native_state_raw', attack)
        self.assertNotIn('mMin', attack)
        self.assertNotIn('mAlreadyPerformed', attack)

    def test_mixed_attack_format_rejected(self):
        data = _plain_data()
        data['enemy_attacks'] = [{'min': 1, 'max': 5, 'mAlreadyPerformed': False}]
        data['enemy_counters'] = [0]
        with self.assertRaises(ValueError):
            build_encounter_state(data)

    def test_canonical_attack_format_accepted(self):
        data = _plain_data()
        data['enemy_attacks'] = [{'min': 1, 'max': 5, 'already_performed': False, 'damage': 1.0}]
        data['enemy_counters'] = [0]
        state = build_encounter_state(data)
        self.assertEqual(state.enemy_attacks[0]['min'], 1)


if __name__ == '__main__':
    unittest.main()
