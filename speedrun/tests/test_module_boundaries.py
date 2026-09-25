"""Guard the telemetry/solver/input separation without a running game."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


class ModuleBoundaryTests(unittest.TestCase):
    def test_legacy_exports_keep_object_identity(self):
        import combat_models
        import attack_input
        import combat_policy
        import combat_telemetry
        import continuous_runner
        import deluxe_optimizer
        import live_runner
        import runner_telemetry
        import x11_controller

        for name in ("Candidate", "DeluxeState", "WordSpec"):
            self.assertIs(getattr(deluxe_optimizer, name), getattr(combat_models, name))
        self.assertIs(deluxe_optimizer.parse_state, combat_telemetry.parse_state)
        self.assertIs(live_runner.X11Keyboard, x11_controller.X11Keyboard)
        self.assertIs(continuous_runner.read_seed, runner_telemetry.read_seed)
        self.assertIs(continuous_runner.select_and_attack_when_native_ready,
                      attack_input.select_and_attack_when_native_ready)
        self.assertIs(continuous_runner.should_use_health_potion,
                      combat_policy.should_use_health_potion)

    def test_low_level_modules_do_not_load_orchestration_or_solver(self):
        root = Path(__file__).resolve().parents[1]
        # Fresh interpreters expose accidental transitive imports that the full
        # suite's already-populated sys.modules would otherwise hide.
        for module in ("combat_models", "combat_telemetry", "runner_telemetry",
                       "x11_controller", "attack_lifecycle", "attack_input",
                       "runner_logging"):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-c",
                     f"import {module}; import sys; "
                     "assert not ({'continuous_runner', 'live_runner', "
                     "'deluxe_optimizer', 'board.solve_board'} & set(sys.modules))"],
                    env={**os.environ, "PYTHONPATH": str(root)},
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_parser_accepts_empty_input_without_game_or_dictionary(self):
        from combat_telemetry import parse_state
        from runner_telemetry import streamed_ready_sequence

        self.assertIsNone(parse_state(""))
        self.assertEqual(streamed_ready_sequence("AUTOMATION_READY_SEQ=8|E", 5), 8)
        self.assertEqual(streamed_ready_sequence("AUTOMATION_READY_SEQ=3|E", 5), 5)
