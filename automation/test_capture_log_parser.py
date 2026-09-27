import unittest
from capture_log_parser import parse_sim_log, partition_sim_log, ParsedRecord


def _block(attack_id, extras=None):
    """Generate a complete AUTOMATION_SIM_* block as a list of lines."""
    lines = [f'AUTOMATION_SIM_BEGIN={attack_id}|E']
    lines.append(f'AUTOMATION_SIM_CREATURE={attack_id}|player|mHealth|10|E')
    lines.append(f'AUTOMATION_SIM_CREATURE={attack_id}|enemy|mHealth|5|E')
    if extras:
        lines.extend(extras)
    lines.append(f'AUTOMATION_SIM_END={attack_id}|E')
    return lines


class ParseSimLogTests(unittest.TestCase):

    def test_normal_complete_block(self):
        lines = _block(1)
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].attack_id, 1)
        self.assertIsNone(records[0].quarantine_reason)

    def test_multiple_sequential_blocks(self):
        lines = _block(1) + _block(2) + _block(3)
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 3)
        self.assertTrue(all(r.quarantine_reason is None for r in records))
        self.assertEqual([r.attack_id for r in records], [1, 2, 3])

    def test_duplicate_attack_id_quarantines_second(self):
        lines = _block(5) + _block(5)
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 2)
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
        self.assertIsNotNone(records[0].quarantine_reason)
        self.assertIn('truncated', records[0].quarantine_reason)

    def test_end_without_begin_quarantined(self):
        lines = ['AUTOMATION_SIM_END=99|E']
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].quarantine_reason)

    def test_wine_console_redraw_lines_skipped(self):
        # Lines starting with ESC[ or consisting of \r are noise
        lines = [
            '\x1b[2J',          # ANSI clear screen
            '\x1b[0;0H',        # ANSI cursor move
            '\r',
        ] + _block(1)
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].quarantine_reason)

    def test_escaped_newlines_in_values(self):
        # The literal two-char sequence \n in a log line should be tolerated
        lines = [
            'AUTOMATION_SIM_BEGIN=2|E',
            r'AUTOMATION_SIM_CREATURE=2|player|mName|Lex\nicon|E',
            'AUTOMATION_SIM_END=2|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].quarantine_reason)

    def test_session_restart_quarantines_new_lower_id(self):
        # After seeing id=5, id=3 is a session restart
        lines = _block(5) + _block(3)
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 2)
        good, quarantined = partition_sim_log(records)
        self.assertEqual(len(good), 1)
        self.assertEqual(good[0].attack_id, 5)
        self.assertEqual(len(quarantined), 1)
        self.assertIn('session restart', quarantined[0].quarantine_reason)

    def test_conflicting_begin_end_ids_quarantined(self):
        lines = [
            'AUTOMATION_SIM_BEGIN=7|E',
            'AUTOMATION_SIM_CREATURE=7|player|mHealth|10|E',
            'AUTOMATION_SIM_END=8|E',  # mismatched ID
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].quarantine_reason)
        self.assertIn('ambiguous', records[0].quarantine_reason)

    def test_non_sim_lines_ignored(self):
        lines = [
            'some gdb output here',
            '[Thread 4 (Thread 0x...)]',
        ] + _block(1)
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].quarantine_reason)

    def test_empty_input_returns_empty(self):
        self.assertEqual(parse_sim_log([]), [])

    def test_begin_without_end_then_valid_block(self):
        lines = (
            ['AUTOMATION_SIM_BEGIN=1|E']  # truncated
            + _block(2)
        )
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 2)
        good, quarantined = partition_sim_log(records)
        self.assertEqual(len(good), 1)
        self.assertEqual(good[0].attack_id, 2)
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].attack_id, 1)

    def test_partition_sim_log(self):
        lines = _block(1) + _block(1)  # second is duplicate
        records = parse_sim_log(lines)
        good, quarantined = partition_sim_log(records)
        self.assertEqual(len(good), 1)
        self.assertEqual(len(quarantined), 1)

    def test_unsupported_marker_in_block(self):
        lines = [
            'AUTOMATION_SIM_BEGIN=4|E',
            'AUTOMATION_SIM_UNSUPPORTED=4|player|effect-queue|E',
            'AUTOMATION_SIM_END=4|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].quarantine_reason)  # parser doesn't quarantine; caller checks fields

    def test_attack_rows_captured(self):
        lines = [
            'AUTOMATION_SIM_BEGIN=6|E',
            'AUTOMATION_SIM_ATTACK=6|enemy|1|mMin|3|E',
            'AUTOMATION_SIM_ATTACK=6|enemy|1|mMax|7|E',
            'AUTOMATION_SIM_END=6|E',
        ]
        records = parse_sim_log(lines)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].quarantine_reason)


if __name__ == '__main__':
    unittest.main()
