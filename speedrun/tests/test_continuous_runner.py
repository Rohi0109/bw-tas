import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from continuous_runner import (
    DEFEATED_RE, MINIGAME_PROMPT_RE, RESET_READY_RE, ZERO_HEALTH_RE,
    boss_finish_strategy,
    enemy_accepts_candidate, is_initial_play_tutorial,
    is_unchanged_combat_snapshot,
    read_latest_dialog, read_screen_blocker, read_seed, sphinx_candidate,
    is_book3_final_gauntlet, should_heal_during_stun, should_use_health_potion,
    should_confirm_book_movie_skip,
    should_use_purification_potion,
    treasure_slots_after, treasure_slots_for_context, treasure_slots_for_state,
)
from deluxe_optimizer import Candidate, DeluxeState


class ContinuousRunnerTests(unittest.TestCase):
    def test_mama_roc_rejects_three_letter_candidates(self):
        mama = replace(self.state(1), enemy="Mama Roc (Boss)")
        short = Candidate("AIR", (0,), 2, 1, None, True, 0.6, 0)
        long = Candidate("AIRS", (0,), 3, 2, None, True, 0.7, 0)

        self.assertFalse(enemy_accepts_candidate(mama, short))
        self.assertTrue(enemy_accepts_candidate(mama, long))

    def test_book_movie_skip_only_arms_after_chapter10_boss_stall(self):
        final_boss = replace(
            self.state(1), chapter=10, enemy="Medusa (Boss)"
        )
        ordinary = replace(final_boss, chapter=9)

        self.assertFalse(should_confirm_book_movie_skip(final_boss, 19))
        self.assertTrue(should_confirm_book_movie_skip(final_boss, 20))
        self.assertFalse(should_confirm_book_movie_skip(ordinary, 20))
        missing_context = replace(final_boss, chapter=-1)
        self.assertTrue(
            should_confirm_book_movie_skip(missing_context, 20, 10)
        )

    def test_minigame_prompt_log_has_book_and_chapter(self):
        event = MINIGAME_PROMPT_RE.search("AUTOMATION_MINIGAME_PROMPT=2|4|7|E")
        self.assertIsNotNone(event)
        self.assertEqual(event.group("book"), "2")
        self.assertEqual(event.group("chapter"), "4")
        self.assertEqual(event.group("sequence"), "7")

    def test_moxie_prompt_pattern_accepts_book1_chapter4(self):
        event = MINIGAME_PROMPT_RE.search("AUTOMATION_MINIGAME_PROMPT=1|4|1|E")
        self.assertIsNotNone(event)
        self.assertEqual(event.group("chapter"), "4")

    def test_moxie_prompt_pattern_accepts_later_checkpoint(self):
        event = MINIGAME_PROMPT_RE.search("AUTOMATION_MINIGAME_PROMPT=1|7|2|E")
        self.assertIsNotNone(event)
        self.assertEqual(event.group("chapter"), "7")

    def test_treasure_context_recovers_route_without_combat_snapshot(self):
        self.assertEqual(treasure_slots_for_context(1, 10), (0, 3, 6))
        self.assertEqual(treasure_slots_for_context(3, 1), (0, 6, 10))

    def test_hydra_head_uses_hydra_treasure_route(self):
        self.assertEqual(treasure_slots_after("Hydra (Head 3)"), (0, 3, 6))

    def test_maladin_unlock_switches_to_wooden_parrot(self):
        self.assertEqual(treasure_slots_after("Maladin (Boss)"), (0, 6, 10))

    def test_book3_keeps_arch_hand_parrot_after_any_boss(self):
        book3 = replace(self.state(1), book=3, enemy="Grim (Boss)")

        self.assertEqual(treasure_slots_for_state(book3), (0, 6, 10))

    def test_boss_finisher_uses_shortest_lethal_strategy(self):
        boss = replace(self.state(1), enemy="Pharaoh of Old (Boss)")
        lethal = Candidate("HIT", (0,), 4, 1, None, True, 0.6, 0)

        self.assertEqual(
            boss_finish_strategy(boss, "overkill-tier", [lethal]),
            "shortest-lethal",
        )

    def test_boss_nonlethal_turn_keeps_chapter_strategy(self):
        boss = replace(self.state(1), enemy="Pharaoh of Old (Boss)", hp=10)
        nonlethal = Candidate("HIT", (0,), 4, -6, None, False, 0.6, 0)

        self.assertEqual(
            boss_finish_strategy(boss, "overkill-tier", [nonlethal]),
            "overkill-tier",
        )

    def test_health_potion_heals_at_or_below_four_before_nonlethal_turn(self):
        low = replace(
            self.state(1), player_hp=3, player_max_hp=7,
            health_potion_available=True,
        )
        threshold = replace(
            self.state(2), player_hp=4, player_max_hp=7,
            health_potion_available=True,
        )
        nonlethal = Candidate("HIT", (0,), 2, -1, None, False, 0.6, 0)

        self.assertTrue(should_use_health_potion(low, nonlethal))
        self.assertTrue(should_use_health_potion(threshold, nonlethal))

    def test_health_potion_skips_low_health_killing_blow(self):
        low = replace(
            self.state(1), player_hp=3, player_max_hp=7,
            health_potion_available=True,
        )
        lethal = Candidate("HIT", (0,), 4, 1, None, True, 0.6, 0)

        self.assertFalse(should_use_health_potion(low, lethal))

    def test_stunned_low_health_heals_even_before_killing_blow(self):
        stunned = replace(
            self.state(1), player_hp=3.5, player_max_hp=6,
            player_stunned=True, health_potion_available=True,
        )
        lethal = Candidate("HIT", (0,), 4, 1, None, True, 0.6, 0)

        self.assertTrue(should_use_health_potion(stunned, lethal))

    def test_stunned_low_health_does_not_click_missing_potion(self):
        stunned = replace(
            self.state(1), player_hp=3.5, player_max_hp=6,
            player_stunned=True, health_potion_available=False,
        )

        self.assertFalse(should_use_health_potion(stunned, None))

    def test_live_stun_heals_at_four_with_available_potion(self):
        stunned = replace(
            self.state(1), player_hp=4, player_max_hp=6,
            health_potion_available=True,
        )

        self.assertTrue(should_heal_during_stun(stunned))

    def test_health_potion_does_not_fire_at_early_full_health(self):
        full = replace(self.state(1), player_hp=3, player_max_hp=3)

        self.assertFalse(should_use_health_potion(full, None))

    def test_hydra_retains_full_heal_rule(self):
        hydra = replace(
            self.state(1), enemy="Hydra (Head 2)",
            player_hp=5, player_max_hp=6, health_potion_available=True,
        )

        self.assertTrue(should_use_health_potion(hydra))

    def test_book3_chapter10_uses_full_heal_and_purify(self):
        gauntlet = replace(
            self.state(1), book=3, chapter=10,
            enemy="Summoned Cerberus", player_hp=6, player_max_hp=7,
            health_potion_available=True,
        )

        self.assertTrue(should_use_health_potion(gauntlet))
        self.assertTrue(should_use_purification_potion(gauntlet))

    def test_summoned_enemy_recovers_missing_chapter10_context(self):
        gauntlet = replace(
            self.state(1), book=3, chapter=-1,
            enemy="Summoned Medusa", player_hp=10.25, player_max_hp=13,
            health_potion_available=True,
        )

        self.assertTrue(is_book3_final_gauntlet(gauntlet))
        self.assertTrue(should_use_health_potion(gauntlet))
        self.assertTrue(should_use_purification_potion(gauntlet))

    def test_other_chapters_do_not_purify_without_known_threat(self):
        ordinary = replace(self.state(1), book=3, chapter=9, enemy="Gargoyle")

        self.assertFalse(should_use_purification_potion(ordinary))

    def test_lua_enemy_transition_event_captures_defeated_name(self):
        match = DEFEATED_RE.search(
            "AUTOMATION_DEFEATED=Cyclops Warrior|E"
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.group("enemy"), "Cyclops Warrior")

    def test_lua_zero_health_event_captures_boss_before_transition(self):
        match = ZERO_HEALTH_RE.search(
            "AUTOMATION_ZERO_HEALTH=Polyphemus (Boss)|E"
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group("enemy"), "Polyphemus (Boss)")

    def test_lua_reset_ready_event_captures_settled_boss(self):
        match = RESET_READY_RE.search(
            "AUTOMATION_BOSS_RESET_READY=Polyphemus (Boss)|E"
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group("enemy"), "Polyphemus (Boss)")

    @staticmethod
    def state(sequence, board="ABCD/EFGH/IJKL/MNOP", hp=3):
        return DeluxeState(
            sequence, board, ("none",) * 16, (0.0,) * 16,
            1, 2, 3, "Cyclops", hp, 5, 0, frozenset(), (),
        )

    def test_sequence_churn_does_not_replay_unchanged_combat(self):
        submitted = self.state(10)

        self.assertTrue(is_unchanged_combat_snapshot(self.state(11), submitted))
        self.assertFalse(
            is_unchanged_combat_snapshot(self.state(11, hp=2.5), submitted)
        )
        self.assertFalse(
            is_unchanged_combat_snapshot(
                self.state(11, board="BCDE/FGHI/JKLM/NOPQ"), submitted
            )
        )

    def test_only_fresh_profile_play_board_triggers_tutorial_override(self):
        board = "SFAE/PFUN/RJDY/TLIS"

        self.assertTrue(is_initial_play_tutorial(board, "levelup", None, 0))
        self.assertTrue(is_initial_play_tutorial(board, "levelup", object(), 0))
        # A fresh launch can briefly consume the prior save's final combat
        # snapshot before Lua publishes this profile's tutorial board.
        self.assertTrue(is_initial_play_tutorial(board, "levelup", None, 1))
        self.assertFalse(is_initial_play_tutorial(board, "conversation", None, 0))
        self.assertFalse(is_initial_play_tutorial("PLAY/AAAA/AAAA/AAAA", "levelup", None, 0))

    def test_treasure_screen_is_recovered_as_click_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text(
                "AUTOMATION_DIALOG=conversation|8|E\n"
                "AUTOMATION_DIALOG=treasure|9|E\n",
                encoding="utf-8",
            )

            self.assertEqual(read_screen_blocker(log), "treasure")

    def test_later_combat_dialog_state_clears_treasure_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text(
                "AUTOMATION_DIALOG=treasure|9|E\n"
                "AUTOMATION_DIALOG=none|10|E\n",
                encoding="utf-8",
            )

            self.assertIsNone(read_screen_blocker(log))

    def test_active_levelup_is_recovered_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text(
                "AUTOMATION_DIALOG=none|14|E\n"
                "AUTOMATION_DIALOG=levelup|15|E\n",
                encoding="utf-8",
            )

            self.assertEqual(read_latest_dialog(log), "levelup")
            self.assertIsNone(read_screen_blocker(log))

    def test_sphinx_uses_fixed_answer(self):
        normal = Candidate("PROPELLED", (0,), 9, 0, None, True, 1.2, 0)
        answer = Candidate("SKY", (1, 2, 3), 1, -8, None, False, 0.6, 0)

        selected, expected = sphinx_candidate(
            "Sphinx (Riddle 1 of 5)", [normal, answer]
        )

        self.assertIs(selected, answer)
        self.assertEqual(expected, "SKY")

    def test_sphinx_missing_answer_reports_required_word(self):
        normal = Candidate("PROPELLED", (0,), 9, 0, None, True, 1.2, 0)

        selected, expected = sphinx_candidate(
            "Sphinx (Riddle 1 of 5)", [normal]
        )

        self.assertIsNone(selected)
        self.assertEqual(expected, "SKY")

    def test_sphinx_last_riddle_uses_normal_combat_strategy(self):
        normal = Candidate("WANTONER", (0,), 7, -2, None, False, 1.15, 0)
        water = Candidate("WATER", (1, 2, 3), 2, -7, None, False, 0.95, 0)

        selected, mode = sphinx_candidate(
            "Sphinx (Last Riddle)", [normal, water]
        )

        self.assertIsNone(selected)
        self.assertIsNone(mode)

    def test_new_board_clears_stale_ready_state(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text(
                "AUTOMATION_READY=ABCD/EFGH/IJKL/MNOP\n"
                "AUTOMATION_BOARD=BCDE/FGHI/JKLM/NOPQ\n",
                encoding="utf-8",
            )

            board, ready, done, chapter = read_seed(log)

        self.assertEqual(board, "BCDE/FGHI/JKLM/NOPQ")
        self.assertFalse(ready)
        self.assertFalse(done)
        self.assertIsNone(chapter)


if __name__ == "__main__":
    unittest.main()
