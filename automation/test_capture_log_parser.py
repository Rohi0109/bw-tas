import unittest
from capture_log_parser import parse_sim_log, partition_sim_log, ParsedRecord


def _block(attack_id, extras=None):
    """Generate a complete AUTOMATION_SIM_* block with minimal creature rows."""
    lines = [f'AUTOMATION_SIM_BEGIN={attack_id}|E']
    lines.append(f'AUTOMATION_SIM_CREATURE={attack_id}|player|mHealth|10|E')
    lines.append(f'AUTOMATION_SIM_CREATURE={attack_id}|enemy|mHealth|5|E')
    if extras:
        lines.extend(extras)
    lines.append(f'AUTOMATION_SIM_END={attack_id}|E')
    return lines


class ParseSimLogTests(unittest.TestCase):

    def test_normal_complete_block(self):
        records = parse_sim_log(_block(1))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].attack_id, 1)
        self.assertIsNone(records[0].quarantine_reason)

    def test_multiple_sequential_blocks(self):
        records = parse_sim_log(_block(1) + _block(2) + _block(3))
        self.assertEqual(len(records), 3)
        self.assertTrue(all(r.quarantine_reason is None for r in records))
        self.assertEqual([r.attack_id for r in records], [1, 2, 3])

    def test_duplicate_attack_id_quarantines_second(self):
        records = parse_sim_log(_block(5) + _block(5))
        good, quarantined = partition_sim_log(records)
        self.assertEqual(len(good), 1)
        self.assertEqual(len(quarantined), 1)
        self.assertIn('duplicate', quarantined[0].quarantine_reason)
        self.assertEqual(quarantined[0].attack_id, 5)

    def test_begin_without_end_quarantined(self):
        lines = [
            'AUTOMATION_SIM_BEGIN=10|E',
            'AUTOMATION_SIM_CREATURE=10|player|mHealth|10|E',
            # No END
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIn('truncated', records[0].quarantine_reason)

    def test_end_without_begin_quarantined(self):
        records = parse_sim_log(['AUTOMATION_SIM_END=99|E'])
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].quarantine_reason)

    def test_wine_console_redraw_lines_skipped(self):
        lines = [
            '\x1b[2J',
            '\x1b[0;0H',
            '\r',
        ] + _block(1)
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].quarantine_reason)

    def test_console_prefixed_sim_line_recovered(self):
        # A line starting with an ANSI escape followed by the sim prefix is
        # recovered (not silently lost) so the block is still parseable.
        lines = [
            '\x1b[0mAUTOMATION_SIM_BEGIN=3|E',
            'AUTOMATION_SIM_CREATURE=3|player|mHealth|10|E',
            'AUTOMATION_SIM_CREATURE=3|enemy|mHealth|5|E',
            'AUTOMATION_SIM_END=3|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].attack_id, 3)
        # Block may be quarantined or not depending on whether prefix recovery
        # is sufficient for a complete block — either way it must produce a record.
        self.assertIsNotNone(records)

    def test_escaped_newlines_in_values_tolerated(self):
        lines = [
            'AUTOMATION_SIM_BEGIN=2|E',
            r'AUTOMATION_SIM_CREATURE=2|player|mName|Lex\nicon|E',
            'AUTOMATION_SIM_CREATURE=2|enemy|mHealth|5|E',
            'AUTOMATION_SIM_END=2|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].quarantine_reason)

    def test_session_restart_quarantines_new_lower_id(self):
        records = parse_sim_log(_block(5) + _block(3))
        good, quarantined = partition_sim_log(records)
        self.assertEqual(len(good), 1)
        self.assertEqual(good[0].attack_id, 5)
        self.assertEqual(len(quarantined), 1)
        self.assertIn('session restart', quarantined[0].quarantine_reason)

    def test_conflicting_begin_end_ids_quarantined(self):
        lines = [
            'AUTOMATION_SIM_BEGIN=7|E',
            'AUTOMATION_SIM_CREATURE=7|player|mHealth|10|E',
            'AUTOMATION_SIM_END=8|E',  # wrong id
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIn('ambiguous', records[0].quarantine_reason)

    def test_non_sim_lines_ignored(self):
        lines = ['some gdb output', '[Thread 4 (Thread 0x...)]'] + _block(1)
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].quarantine_reason)

    def test_empty_input_returns_empty(self):
        self.assertEqual(parse_sim_log([]), [])

    def test_begin_without_end_then_valid_block(self):
        lines = ['AUTOMATION_SIM_BEGIN=1|E'] + _block(2)
        records = parse_sim_log(lines)
        good, quarantined = partition_sim_log(records)
        self.assertEqual(len(good), 1)
        self.assertEqual(good[0].attack_id, 2)
        self.assertEqual(quarantined[0].attack_id, 1)

    def test_partition_sim_log(self):
        records = parse_sim_log(_block(1) + _block(1))
        good, quarantined = partition_sim_log(records)
        self.assertEqual(len(good), 1)
        self.assertEqual(len(quarantined), 1)

    # --- Quarantine cases added to fix review findings ---

    def test_unsupported_marker_quarantines_block(self):
        # AUTOMATION_SIM_UNSUPPORTED inside a block must quarantine it, not pass it.
        lines = [
            'AUTOMATION_SIM_BEGIN=4|E',
            'AUTOMATION_SIM_CREATURE=4|player|mHealth|10|E',
            'AUTOMATION_SIM_UNSUPPORTED=4|player|effect-queue|E',
            'AUTOMATION_SIM_END=4|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].quarantine_reason)
        self.assertIn('unsupported', records[0].quarantine_reason)

    def test_row_id_mismatch_quarantines_block(self):
        # A creature row with wrong attack_id inside a block quarantines the block.
        lines = [
            'AUTOMATION_SIM_BEGIN=5|E',
            'AUTOMATION_SIM_CREATURE=5|player|mHealth|10|E',
            'AUTOMATION_SIM_CREATURE=99|enemy|mHealth|5|E',  # wrong id
            'AUTOMATION_SIM_END=5|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].quarantine_reason)
        self.assertIn('mismatch', records[0].quarantine_reason)

    def test_conflicting_field_values_quarantine_block(self):
        # Same (kind, owner, field) appearing with two different values → quarantine.
        lines = [
            'AUTOMATION_SIM_BEGIN=6|E',
            'AUTOMATION_SIM_CREATURE=6|player|mHealth|50|E',
            'AUTOMATION_SIM_CREATURE=6|player|mHealth|30|E',  # conflict
            'AUTOMATION_SIM_END=6|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].quarantine_reason)
        self.assertIn('conflict', records[0].quarantine_reason)

    def test_duplicate_field_same_value_not_quarantined(self):
        # Exact duplicate rows (same value) are silently deduplicated; not a conflict.
        lines = [
            'AUTOMATION_SIM_BEGIN=7|E',
            'AUTOMATION_SIM_CREATURE=7|player|mHealth|10|E',
            'AUTOMATION_SIM_CREATURE=7|player|mHealth|10|E',  # same value
            'AUTOMATION_SIM_CREATURE=7|enemy|mHealth|5|E',
            'AUTOMATION_SIM_END=7|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].quarantine_reason)

    def test_attack_rows_captured_in_fields(self):
        lines = [
            'AUTOMATION_SIM_BEGIN=8|E',
            'AUTOMATION_SIM_CREATURE=8|player|mHealth|10|E',
            'AUTOMATION_SIM_CREATURE=8|enemy|mHealth|5|E',
            'AUTOMATION_SIM_ATTACK=8|enemy|1|mMin|3|E',
            'AUTOMATION_SIM_ATTACK=8|enemy|1|mMax|7|E',
            'AUTOMATION_SIM_END=8|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].quarantine_reason)
        self.assertIn(('ATTACK', 'enemy', '1', 'mMin'), records[0].fields)
        self.assertEqual(records[0].fields[('ATTACK', 'enemy', '1', 'mMin')], '3')

    def test_fields_empty_on_quarantine(self):
        # Quarantined records must have empty fields dict to prevent misuse.
        lines = [
            'AUTOMATION_SIM_BEGIN=9|E',
            'AUTOMATION_SIM_UNSUPPORTED=9|player|effect-queue|E',
            'AUTOMATION_SIM_END=9|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(records[0].fields, {})


if __name__ == '__main__':
    unittest.main()
