"""Actual log/CLI boundary tests; synthetic data is never native parity evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from assemble_captures import assemble_captures_from_log, assemble_encounter_from_fields
from test_assemble_captures import _make_complete_log_lines, _log_extra, _make_fields, _minimal_attack, _EXTRA


class CapturePipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def run_log(self, lines, extra):
        path = self.root / 'capture.log'
        path.write_text('\n'.join(lines))
        return assemble_captures_from_log(path, extra)

    def lines(self, attack_id=1, effects=0):
        additions = [f'AUTOMATION_SIM_COLLECTION={attack_id}|enemy|attacks|1|E',
                     f'AUTOMATION_SIM_COLLECTION={attack_id}|enemy|effects|0|E',
                     f'AUTOMATION_SIM_COLLECTION={attack_id}|player|effects|{effects}|E']
        if effects:
            additions.append(f'AUTOMATION_SIM_EFFECT={attack_id}|player|3|mDuration|5|E')
        return _make_complete_log_lines(attack_id, extra_lines=additions)

    def test_complete_sidecar_cli_preserves_two_boundaries(self):
        first = _log_extra()
        second = copy.deepcopy(first)
        second.update(attack_id=2, selected_action='BAD', teacher_forced=True,
                      unsupported_state=['external-limitation'])
        second['observed']['enemy_hp'] = 40
        log = self.root / 'capture.log'
        log.write_text('\n'.join(self.lines(1) + self.lines(2)))
        sidecar = self.root / 'boundaries.json'
        sidecar.write_text(json.dumps({'boundaries': {'1': first, '2': second}}))
        output = self.root / 'report.json'
        command = [sys.executable, str(Path(__file__).parents[1] / 'assemble_captures.py'),
                   str(log), '--boundaries', str(sidecar), '--output', str(output)]
        process = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(output.read_text())
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['quarantined'], [])
        one, two = report['valid']
        self.assertEqual(one['eligibility'], 'unsupported_state')
        self.assertEqual(two['eligibility'], 'teacher_forced')
        self.assertEqual(two['fixture']['pre_submit']['selected_action'], 'BAD')
        self.assertEqual(one['fixture']['observed']['enemy_hp'], 50)
        self.assertEqual(two['fixture']['observed']['enemy_hp'], 40)
        self.assertEqual(two['fixture']['pre_submit']['enemy_attack_keys'], ['0'])
        self.assertIn('external-limitation', two['unsupported_fields'])
        self.assertIn('attack_state_mapping_unconfirmed', one['unsupported_fields'])
        self.assertFalse(report['full_game_parity'])
        self.assertEqual(len(report['source_sha256']), 64)
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_single_sidecar_cannot_relabel_second_turn(self):
        result = self.run_log(self.lines(1) + self.lines(2), _log_extra())
        self.assertEqual([r['attack_id'] for r in result['valid']], [1])
        self.assertEqual([r['attack_id'] for r in result['errors']], [2])
        self.assertTrue(result['errors'][0]['raw_fields'])

    def test_missing_identity_never_borrows_record_id(self):
        extra = _log_extra()
        del extra['attack_id']
        self.assertEqual(len(self.run_log(self.lines(), extra)['errors']), 1)

    def test_effects_preserved_without_unsupported_marker(self):
        report = self.run_log(self.lines(effects=1), _log_extra())
        row = report['valid'][0]
        self.assertEqual(row['fixture']['pre_submit']['player_effects'],
                         [{'native_key': '3', 'mDuration': '5'}])
        self.assertIn('player_effects', row['unsupported_fields'])
        self.assertIn('effects_unsupported', row['unsupported_fields'])

    def test_missing_counts_are_unsupported_not_assumed_empty(self):
        report = self.run_log(_make_complete_log_lines(1), _log_extra())
        self.assertIn('player_effect_presence_unconfirmed', report['valid'][0]['unsupported_fields'])

    def test_conflicting_count_and_missing_counter_are_errors(self):
        for lines in (self.lines(effects=0)[:-1] +
                      ['AUTOMATION_SIM_EFFECT=1|player|3|mDuration|5|E', 'AUTOMATION_SIM_END=1|E'],
                      [line for line in self.lines() if '|mRateCounter|' not in line]):
            result = self.run_log(lines, _log_extra())
            self.assertEqual(result['valid'], [])
            self.assertEqual(len(result['errors']), 1)

    def test_quarantine_and_incomplete_are_separate(self):
        lines = self.lines() + ['AUTOMATION_SIM_BEGIN=2|E']
        result = self.run_log(lines, _EXTRA)  # no board/RNG sidecar
        self.assertEqual(result['valid'], [])
        self.assertEqual([r['attack_id'] for r in result['errors']], [1])
        self.assertEqual([r['attack_id'] for r in result['quarantined']], [2])

    def test_player_attack_is_not_used_by_enemy(self):
        lines = self.lines()[:-1] + [
            'AUTOMATION_SIM_ATTACK=1|player|99|mMin|999|E', 'AUTOMATION_SIM_END=1|E']
        pre = self.run_log(lines, _log_extra())['valid'][0]['fixture']['pre_submit']
        self.assertEqual(pre['enemy_counters'], [0])
        self.assertEqual(pre['enemy_attack_keys'], ['0'])

    def test_inline_board_and_conflict(self):
        lines = self.lines()[:-1] + ['AUTOMATION_SIM_BOARD=1|ABCD/EFGH/IJKL/MNOP|E',
                                    'AUTOMATION_SIM_END=1|E']
        self.assertEqual(len(self.run_log(lines, _log_extra())['valid']), 1)
        extra = _log_extra()
        extra['captured_state']['board'] = 'ZZZZ/ZZZZ/ZZZZ/ZZZZ'
        self.assertEqual(len(self.run_log(lines, extra)['errors']), 1)

    def test_exact_tile_and_rng_indices(self):
        for kind, prefix, size in [('GEMS', (), 16), ('TILE_POWERS', (), 16),
                                   ('ENGINE_RNG', ('words',), 624)]:
            for invalid in (str(size), '-1', '01'):
                fields = _make_fields([_minimal_attack()])
                key = (kind,) + prefix + ('0',)
                fields[(kind,) + prefix + (invalid,)] = fields.pop(key)
                with self.subTest(kind=kind, invalid=invalid), self.assertRaises(ValueError):
                    assemble_encounter_from_fields(fields, _EXTRA)

    def test_partial_inline_capture_cannot_be_replaced(self):
        fields = _make_fields([_minimal_attack()])
        del fields[('ENGINE_RNG', 'words', '7')]
        with self.assertRaisesRegex(ValueError, 'incomplete inline RNG'):
            assemble_encounter_from_fields(fields, _log_extra())

    def test_invalid_input_is_reported_without_crashing_cli(self):
        for value in ('nan', 'inf', 'not-a-number'):
            lines = [line.replace('|mHealth|100.0|', f'|mHealth|{value}|') for line in self.lines()]
            result = self.run_log(lines, _log_extra())
            self.assertEqual(len(result['errors']), 1)
            json.dumps(result, allow_nan=False)

    def test_empty_boolean_is_not_false(self):
        lines = [line.replace('|mAlreadyPerformed|false|', '|mAlreadyPerformed||')
                 for line in self.lines()]
        report = self.run_log(lines, _log_extra())
        self.assertEqual(len(report['errors']), 1)
        self.assertEqual(report['valid'], [])

    def test_bad_owner_is_not_silently_discarded(self):
        lines = [line.replace('|enemy|', '|unknown|') for line in self.lines()]
        self.assertEqual(len(self.run_log(lines, _log_extra())['errors']), 1)


if __name__ == '__main__':
    unittest.main()
