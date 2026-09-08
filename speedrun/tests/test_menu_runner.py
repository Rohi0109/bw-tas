import unittest

from menu_runner import (
    MenuTiming, event_driven_reset_timing, reset_from_battle,
    start_from_main_menu,
)


class RecordingController:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(delay):
            self.calls.append((name, delay))
        return record


class MenuRunnerTests(unittest.TestCase):
    def test_event_driven_reset_does_not_sleep_after_adventure(self):
        timing = event_driven_reset_timing()

        self.assertEqual(timing.after_battle_menu, 0.35)
        self.assertEqual(timing.after_quit_prompt, 1.00)
        self.assertEqual(timing.after_quit, 1.10)
        self.assertEqual(timing.after_adventure, 0.0)

    def test_start_resumes_same_chapter_without_extra_click(self):
        controller = RecordingController()
        timing = MenuTiming(after_adventure=1.2, after_enter=1.5)

        start_from_main_menu(controller, timing)

        self.assertEqual(controller.calls, [("start_adventure", 1.2)])

    def test_chapter_start_clicks_map_enter(self):
        controller = RecordingController()
        timing = MenuTiming(after_adventure=1.2, after_enter=1.5)

        start_from_main_menu(controller, timing, enter_chapter=True)

        self.assertEqual(controller.calls, [
            ("start_adventure", 1.2),
            ("enter_chapter", 1.5),
        ])

    def test_reset_matches_wr_sequence(self):
        controller = RecordingController()
        timing = MenuTiming(0.3, 0.4, 1.0, 1.2, 1.5)

        reset_from_battle(controller, timing)

        self.assertEqual(controller.calls, [
            ("open_battle_menu", 0.3),
            ("quit_to_main_menu", 0.4),
            ("confirm_quit_to_main_menu", 1.0),
            ("start_adventure", 1.2),
        ])

    def test_chapter_reset_includes_map_enter(self):
        controller = RecordingController()
        timing = MenuTiming(0.3, 0.4, 1.0, 1.2, 1.5)

        reset_from_battle(controller, timing, enter_chapter=True)

        self.assertEqual(controller.calls[-2:], [
            ("start_adventure", 1.2),
            ("enter_chapter", 1.5),
        ])


if __name__ == "__main__":
    unittest.main()
