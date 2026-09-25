"""Manual Chapter 9 skip trace: Enter -> prompt -> Yes callback -> treasure."""

import unittest
from unittest.mock import Mock

from runner_telemetry import latest_unresolved_minigame_prompt
from x11_controller import X11Keyboard
from runner_telemetry import CHAPTER_MAP_RE
from continuous_runner import chapter_map_confirms_menu_reentry, boss_replay_is_fresh
from types import SimpleNamespace


ENTER = ('AUTOMATION_CHAPTER_MAP=3|9|nil|9|true|E\n'
         'AUTOMATION_CHAPTER_ACTION=continue|E\n')
PROMPT = 'AUTOMATION_MINIGAME_PROMPT=3|9|17|E\n'
CALLBACK = 'AUTOMATION_CHAPTER_ACTION=minigame-callback|E\n'
TREASURE = ('AUTOMATION_CHAPTER_MAP=3|9|nil|9|false|E\n'
            'AUTOMATION_TREASURE_CONTEXT=3|9|9|E\n')


class MoxieHandoffTests(unittest.TestCase):
    def test_cached_full_health_mummy_snapshot_is_not_a_replay(self):
        stale = SimpleNamespace(sequence=233, hp=26, max_hp=26)
        self.assertFalse(boss_replay_is_fresh(stale, 233))
        self.assertFalse(boss_replay_is_fresh(stale, None))
        fresh = SimpleNamespace(sequence=234, hp=26, max_hp=26)
        self.assertTrue(boss_replay_is_fresh(fresh, 233))
        damaged = SimpleNamespace(sequence=234, hp=5, max_hp=26)
        self.assertFalse(boss_replay_is_fresh(damaged, 233))

    def test_dracula_disabled_map_ends_adventure_retry_ownership(self):
        # Actual failing trace: no enabled-map edge before chapter 300 opened.
        event = CHAPTER_MAP_RE.search('AUTOMATION_CHAPTER_MAP=3|10|nil|10|false|E')
        enabled = event.group('enabled') == 'true'
        self.assertFalse(enabled)  # do not send Enter yet
        self.assertTrue(chapter_map_confirms_menu_reentry(enabled))

    def test_enter_alone_does_not_authorize_yes(self):
        self.assertIsNone(latest_unresolved_minigame_prompt(ENTER))

    def test_manual_trace_resolves_prompt_before_treasure_selection(self):
        event = latest_unresolved_minigame_prompt(ENTER + PROMPT)
        self.assertEqual(event.group('sequence'), '17')
        self.assertIsNone(latest_unresolved_minigame_prompt(ENTER + PROMPT + CALLBACK))
        self.assertIsNone(latest_unresolved_minigame_prompt(ENTER + PROMPT + CALLBACK + TREASURE))

    def test_treasure_proves_resolution_even_if_callback_is_missing(self):
        self.assertIsNone(latest_unresolved_minigame_prompt(ENTER + PROMPT + TREASURE))
        legacy = 'AUTOMATION_DIALOG=treasure|525|E\n'
        self.assertIsNone(latest_unresolved_minigame_prompt(PROMPT + legacy))

    def test_old_callback_does_not_hide_new_prompt(self):
        event = latest_unresolved_minigame_prompt(PROMPT + CALLBACK + TREASURE +
                    'AUTOMATION_MINIGAME_PROMPT=3|10|18|E\n')
        self.assertEqual(event.group('sequence'), '18')

    def test_skip_uses_left_yes_button(self):
        controller = object.__new__(X11Keyboard)
        controller.layout = 'deluxe'
        controller.window = 1
        controller._size = Mock(return_value=(800, 600))
        controller.focus = Mock()
        controller.click = Mock()
        controller.confirm_skip_minigame(0)
        controller.focus.assert_called_once()
        controller.click.assert_called_once_with(332, 409, 0)
