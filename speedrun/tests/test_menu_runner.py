import unittest

from menu_runner import MenuTiming, reset_from_battle, start_from_main_menu


class RecordingController:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(delay):
            self.calls.append((name, delay))
        return record


class MenuRunnerTests(unittest.TestCase):
    def test_start_enters_adventure_then_current_chapter(self):
        controller = RecordingController()
        timing = MenuTiming(after_adventure=1.2, after_enter=1.5)

        start_from_main_menu(controller, timing)

        self.assertEqual(controller.calls, [
            ("start_adventure", 1.2),
            ("enter_chapter", 1.5),
        ])

    def test_reset_matches_wr_sequence(self):
        controller = RecordingController()
        timing = MenuTiming(0.3, 1.0, 1.2, 1.5)

        reset_from_battle(controller, timing)

        self.assertEqual(controller.calls, [
            ("open_battle_menu", 0.3),
            ("quit_to_main_menu", 1.0),
            ("start_adventure", 1.2),
            ("enter_chapter", 1.5),
        ])


if __name__ == "__main__":
    unittest.main()
