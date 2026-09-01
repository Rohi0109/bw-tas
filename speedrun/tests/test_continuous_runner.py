import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from continuous_runner import (
    ATTACK_SUBMITTED_RE, DEFEATED_RE, DIALOG_ACTIVE_RE, DIALOG_PULSE_RE,
    INCAP_OVERLAY_RE, MINIGAME_PROMPT_RE, PLAYER_STUNNED_RE,
    RESET_READY_RE,
    ZERO_HEALTH_RE,
    boss_finish_strategy,
    boss_reset_dialog_recovery_allowed, clear_stale_treasure_on_ready,
    clear_stale_treasure_transition,
    completes_early_ready,
    dialogue_pulse_suppressed,
    enemy_accepts_candidate, health_potion_confirmed, is_initial_play_tutorial,
    is_unchanged_combat_snapshot,
    latest_active_incapacitation_event, latest_incapacitation_state,
    latest_unresolved_incapacitation_overlay,
    lua_runtime_is_waiting,
    read_latest_dialog, read_screen_blocker,
    ready_sequence_is_fresh,
    read_seed, sphinx_candidate,
    state_is_incapacitated,
    telemetry_context,
    unresolved_play_tutorial,
    sphinx_allows_damage_fallback,
    is_book3_final_gauntlet, should_use_health_potion,
    should_use_powerup_potion,
    should_confirm_book_movie_skip,
    immediate_defeated_reset_reason,
    should_arm_boss_reset_on_zero_health,
    incapacitation_recovery_action,
    should_use_purification_potion,
    treasure_slots_after, treasure_slots_for_context, treasure_slots_for_state,
)
from deluxe_optimizer import Candidate, DeluxeState
from live_runner import X11Keyboard


class ContinuousRunnerTests(unittest.TestCase):
    def test_lua_runtime_wait_marker_is_detected_near_log_tail(self):
        marker = "Program in waiting. Type go() or press F5 to continue execution."

        self.assertTrue(lua_runtime_is_waiting("old output\n" + marker))
        self.assertTrue(lua_runtime_is_waiting(marker + "\n\0\0> \b"))
        self.assertFalse(lua_runtime_is_waiting(marker + "\nAUTOMATION_SYNC=1"))
        self.assertFalse(lua_runtime_is_waiting("AUTOMATION_BOARD=ABCD/EFGH/IJKL/MNOP"))

    def test_startup_recovers_existing_incapacitation(self):
        normal = self.state(1)

        self.assertFalse(state_is_incapacitated(None))
        self.assertFalse(state_is_incapacitated(normal))
        self.assertTrue(state_is_incapacitated(replace(normal, player_stunned=True)))
        self.assertTrue(state_is_incapacitated(replace(normal, player_frozen=True)))
        self.assertTrue(state_is_incapacitated(replace(normal, player_petrified=True)))

    def test_startup_replays_incapacitation_edges_after_snapshot(self):
        normal = self.state(1)
        stunned = "AUTOMATION_PLAYER_STUNNED=1|4.75|5|0|E\n"
        recovered = stunned + "AUTOMATION_PLAYER_STUNNED=0|4.75|5|0|E\n"

        self.assertTrue(latest_incapacitation_state(stunned, normal))
        self.assertFalse(latest_incapacitation_state(recovered, normal))
        self.assertTrue(latest_incapacitation_state(
            "AUTOMATION_PLAYER_FROZEN=1|3|5|0|E\n", normal,
        ))

    def test_startup_preserves_active_incapacitation_potion_telemetry(self):
        text = (
            "AUTOMATION_PLAYER_STUNNED=1|3|6|1|0|E\n"
            "AUTOMATION_PLAYER_STUNNED=0|3|6|1|0|E\n"
            "AUTOMATION_PLAYER_PETRIFIED=1|6|6|1|1|E\n"
        )

        event = latest_active_incapacitation_event(text)

        self.assertEqual(event.group("kind"), "PETRIFIED")
        self.assertEqual(event.group("health_potion"), "1")
        self.assertEqual(event.group("purify_potion"), "1")

    def test_startup_recovers_final_overlay_after_status_flag_clears(self):
        text = (
            "AUTOMATION_READY_SEQ=73|E\n"
            "AUTOMATION_PLAYER_PETRIFIED=1|6|6|1|1|E\n"
            "AUTOMATION_INCAP_OVERLAY=petrified|petrify2done|E\n"
            "AUTOMATION_PLAYER_PETRIFIED=0|2|6|1|1|E\n"
        )

        overlay = latest_unresolved_incapacitation_overlay(text)

        self.assertEqual(overlay.group("kind"), "petrified")
        self.assertEqual(overlay.group("frame"), "petrify2done")
        self.assertIsNone(latest_unresolved_incapacitation_overlay(
            text + "AUTOMATION_READY_SEQ=74|E\n"
        ))

    def test_native_attack_submission_event_captures_enemy(self):
        event = ATTACK_SUBMITTED_RE.search(
            "AUTOMATION_ATTACK_SUBMITTED=Alexander|E"
        )

        self.assertEqual(event.group("enemy"), "Alexander")

    def test_alexander_confirmed_defeat_triggers_early_reset(self):
        alexander = replace(
            self.state(1), enemy="Alexander", hp=2, max_hp=2,
        )

        self.assertEqual(
            immediate_defeated_reset_reason(
                alexander, "Alexander", set(), 1,
            ),
            "after Alexander, before boss entrance",
        )
        self.assertIsNone(
            immediate_defeated_reset_reason(
                alexander, "Trojan Captain", set(), 1,
            )
        )
        self.assertFalse(should_arm_boss_reset_on_zero_health(alexander))

    def test_chapter_boss_zero_health_arms_save_ready_reset(self):
        boss = replace(
            self.state(1), enemy="Polydamas (Boss)", hp=0, max_hp=3, stage=6,
        )

        self.assertTrue(should_arm_boss_reset_on_zero_health(boss))
        self.assertIsNone(
            immediate_defeated_reset_reason(
                boss, "Polydamas (Boss)", set(), 1,
            )
        )

    def test_only_last_sphinx_riddle_arms_save_ready_reset(self):
        earlier = replace(self.state(1), enemy="Sphinx (Riddle 4 of 5)")
        final = replace(self.state(1), enemy="Sphinx (Last Riddle)")

        self.assertFalse(should_arm_boss_reset_on_zero_health(earlier))
        self.assertTrue(should_arm_boss_reset_on_zero_health(final))

    def test_petrify_edges_include_native_health_state(self):
        started = PLAYER_STUNNED_RE.search(
            "AUTOMATION_PLAYER_PETRIFIED=1|6|6|1|E"
        )
        ended = PLAYER_STUNNED_RE.search(
            "AUTOMATION_PLAYER_PETRIFIED=0|2.0|6|1|E"
        )

        self.assertEqual(started.group("kind"), "PETRIFIED")
        self.assertEqual(ended.group("active"), "0")
        self.assertEqual(float(ended.group("hp")), 2.0)

    def test_frozen_edges_and_native_overlay_are_recognized(self):
        frozen = PLAYER_STUNNED_RE.search(
            "AUTOMATION_PLAYER_FROZEN=1|3.5|6|1|1|E"
        )
        overlay = INCAP_OVERLAY_RE.search(
            "AUTOMATION_INCAP_OVERLAY=frozen|breakfrozen|2|6|1|0|E"
        )

        self.assertEqual(frozen.group("kind"), "FROZEN")
        self.assertEqual(float(frozen.group("hp")), 3.5)
        self.assertEqual(frozen.group("purify_potion"), "1")
        self.assertEqual(overlay.group("kind"), "frozen")
        self.assertEqual(overlay.group("frame"), "breakfrozen")
        self.assertEqual(float(overlay.group("hp")), 2)

    def test_incapacitation_recovery_priority(self):
        cases = (
            (True, True, 2, "purify"),
            (False, True, 2, "heal_then_continue"),
            (False, True, 4, "heal_then_continue"),
            (False, True, 4.25, "continue"),
            (False, False, 2, "continue"),
        )
        for purify, health, hp, expected in cases:
            with self.subTest(
                purify=purify, health=health, hp=hp,
            ):
                self.assertEqual(
                    incapacitation_recovery_action(
                        purify_available=purify,
                        health_available=health,
                        player_hp=hp,
                        player_max_hp=6,
                    ),
                    expected,
                )

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

    def test_health_potion_is_saved_before_ordinary_killing_blow(self):
        low = replace(
            self.state(1), player_hp=3, player_max_hp=7,
            health_potion_available=True,
        )
        lethal = Candidate("HIT", (0,), 4, 1, None, True, 0.6, 0)

        self.assertFalse(should_use_health_potion(low, lethal))

    def test_sphinx_low_health_heals_before_fallback_killing_blow(self):
        sphinx = replace(
            self.state(1), enemy="Sphinx (Riddle 3 of 5)",
            player_hp=1, player_max_hp=7, health_potion_available=True,
        )
        lethal = Candidate("JUBILANTLY", (0,), 10.75, 1.75, None, True, 1.45, 0)

        self.assertTrue(should_use_health_potion(sphinx, lethal))

    def test_powerup_potion_is_used_only_when_it_removes_an_attack(self):
        available = replace(
            self.state(1), hp=7, attack_potion_available=True,
        )
        unavailable = replace(available, attack_potion_available=False)
        converts_to_lethal = Candidate("POWER", (0,), 6, -1, None, False, 0.8, 0)
        still_nonlethal = replace(converts_to_lethal, damage=3, overkill=-4)
        already_lethal = replace(converts_to_lethal, damage=7, lethal=True)

        self.assertTrue(should_use_powerup_potion(available, converts_to_lethal))
        self.assertFalse(should_use_powerup_potion(available, still_nonlethal))
        self.assertFalse(should_use_powerup_potion(available, already_lethal))
        self.assertFalse(should_use_powerup_potion(unavailable, converts_to_lethal))

    def test_powerup_uses_native_twenty_five_percent_boost(self):
        circe = replace(
            self.state(1), enemy="Circe (Boss)", hp=10,
            attack_potion_available=True,
        )
        five_damage = Candidate("IRRELATIVE", (0,), 5, -5, None, False, 1.35, 0)
        serpent = replace(circe, enemy="Enchanted Serpent", hp=7)
        serpent_attack = replace(five_damage, damage=6.25, overkill=-0.75)

        self.assertFalse(should_use_powerup_potion(circe, five_damage))
        self.assertTrue(should_use_powerup_potion(serpent, serpent_attack))

    def test_stunned_low_health_heals_even_before_killing_blow(self):
        stunned = replace(
            self.state(1), player_hp=3.5, player_max_hp=6,
            player_stunned=True, health_potion_available=True,
        )
        lethal = Candidate("HIT", (0,), 4, 1, None, True, 0.6, 0)

        self.assertTrue(should_use_health_potion(stunned, lethal))

    def test_petrified_low_health_heals_even_before_killing_blow(self):
        petrified = replace(
            self.state(1), player_hp=5, player_max_hp=6,
            player_petrified=True, health_potion_available=True,
        )
        lethal = Candidate("HIT", (0,), 4, 1, None, True, 0.6, 0)

        self.assertTrue(should_use_health_potion(petrified, lethal))

    def test_frozen_low_health_heals_even_before_killing_blow(self):
        frozen = replace(
            self.state(1), player_hp=3.5, player_max_hp=6,
            player_frozen=True, health_potion_available=True,
        )
        lethal = Candidate("HIT", (0,), 4, 1, None, True, 0.6, 0)

        self.assertTrue(should_use_health_potion(frozen, lethal))

    def test_health_potion_requires_native_consumption_or_hp_confirmation(self):
        before = replace(
            self.state(1), player_hp=4, player_max_hp=6,
            health_potion_available=True,
        )

        self.assertFalse(health_potion_confirmed(before, before))
        self.assertTrue(health_potion_confirmed(
            before, replace(before, health_potion_available=False)
        ))
        self.assertTrue(health_potion_confirmed(
            before, replace(before, player_hp=6)
        ))

    def test_stunned_low_health_does_not_click_missing_potion(self):
        stunned = replace(
            self.state(1), player_hp=3.5, player_max_hp=6,
            player_stunned=True, health_potion_available=False,
        )

        self.assertFalse(should_use_health_potion(stunned, None))

    def test_health_potion_does_not_fire_at_early_full_health(self):
        full = replace(self.state(1), player_hp=3, player_max_hp=3)

        self.assertFalse(should_use_health_potion(full, None))

    def test_hydra_retains_full_heal_rule(self):
        hydra = replace(
            self.state(1), enemy="Hydra (Head 2)",
            player_hp=5, player_max_hp=6, health_potion_available=True,
        )

        self.assertTrue(should_use_health_potion(hydra))

    def test_resisted_stun_does_not_force_heal_before_lethal_boss_word(self):
        cerberus = replace(
            self.state(1), enemy="Cerberus (Boss)", hp=5.5,
            player_hp=4, player_max_hp=6, health_potion_available=True,
            player_stunned=False,
        )
        predicted_lethal = Candidate(
            "HYPERMANIAS", (0,), 5.75, 0.25, None, True, 1.45, 0,
        )

        self.assertFalse(should_use_health_potion(cerberus, predicted_lethal))

    def test_low_health_ordinary_lethal_attack_preserves_potion(self):
        manes = replace(
            self.state(1), enemy="Manes", hp=3,
            player_hp=2.25, player_max_hp=5, health_potion_available=True,
        )
        lethal = Candidate("FEVERWORT", (0,), 4, 1, None, True, 1.25, 0)

        self.assertFalse(should_use_health_potion(manes, lethal))

    def test_hydra_purifies_lingering_status_even_on_lethal_word(self):
        hydra = replace(
            self.state(1), enemy="Hydra (Head 3)",
            player_has_damage_over_time=True,
        )
        lethal = Candidate("FINISH", (0,), 5, 1, None, True, 0.8, 0)

        self.assertTrue(should_use_purification_potion(hydra, lethal))
        self.assertFalse(should_use_purification_potion(
            replace(hydra, player_has_damage_over_time=False), lethal,
        ))

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

    def test_damaged_basilisk_does_not_imply_lex_needs_purify(self):
        basilisk = replace(
            self.state(1), book=1, chapter=10, enemy="Lesser Basilisk",
            hp=12, max_hp=25, player_petrified=False,
            player_has_damage_over_time=False,
        )
        attack = Candidate("FIGUREHEAD", (0,), 9.25, -2.75, None, False, 1.35, 0)

        self.assertFalse(should_use_purification_potion(basilisk, attack))

    def test_enyo_lethal_word_does_not_waste_health_or_purify(self):
        burning = replace(
            self.state(1), enemy="Enyo", player_hp=5.25, player_max_hp=6,
            health_potion_available=True, player_has_damage_over_time=True,
        )
        lethal = Candidate("FASTENERS", (0,), 7, 0.25, None, True, 1.25, 0)

        self.assertFalse(should_use_health_potion(burning, lethal))
        self.assertFalse(should_use_purification_potion(burning, lethal))
        self.assertTrue(
            should_use_purification_potion(
                burning, replace(lethal, lethal=False)
            )
        )

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
        self.assertFalse(
            is_unchanged_combat_snapshot(
                replace(self.state(11), player_hp=2.25), submitted
            )
        )
        self.assertFalse(
            is_unchanged_combat_snapshot(
                replace(
                    self.state(11),
                    zero_damage=(False,) * 5 + (True,) + (False,) * 10,
                ),
                submitted,
            )
        )

    def test_completed_snapshot_rearms_an_early_ready(self):
        state = self.state(80, board="NAEM/DYII/QRDP/OWIQ")

        self.assertTrue(completes_early_ready(state, "NAEM/DYII/QRDP/OWIQ"))
        self.assertFalse(completes_early_ready(state, "GGII/DNRA/QWIP/OUUQ"))
        self.assertFalse(completes_early_ready(state, None))

    def test_only_fresh_profile_play_board_triggers_tutorial_override(self):
        board = "SFAE/PFUN/RJDY/TLIS"

        self.assertTrue(is_initial_play_tutorial(board, "interrupt", None, 0))
        self.assertTrue(is_initial_play_tutorial(board, "interrupt", object(), 0))
        # A fresh launch can briefly consume the prior save's final combat
        # snapshot before Lua publishes this profile's tutorial board.
        self.assertTrue(is_initial_play_tutorial(board, "interrupt", None, 1))
        self.assertFalse(is_initial_play_tutorial(board, "conversation", None, 0))
        self.assertFalse(is_initial_play_tutorial("PLAY/AAAA/AAAA/AAAA", "interrupt", None, 0))

    def test_active_play_marker_is_recovered_at_startup(self):
        active = (
            "mangled AUTOMATION_BOARD=SFAE/PFUN/RJD\n"
            "AUTOMATION_PLAY_TUTORIAL=2|E\n"
            "AUTOMATION_DIALOG_PULSE=interrupt|2|9|E\n"
        )
        closed = active + "AUTOMATION_DIALOG_INACTIVE=2|E\n"

        self.assertTrue(unresolved_play_tutorial(active))
        self.assertFalse(unresolved_play_tutorial(closed))

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

    def test_native_ready_clears_stale_treasure_transition(self):
        self.assertEqual(
            clear_stale_treasure_on_ready("treasure", True),
            (None, False),
        )

    def test_active_levelup_is_recovered_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "lua.log"
            log.write_text(
                "AUTOMATION_DIALOG_INACTIVE=14|E\n"
                "AUTOMATION_DIALOG_ACTIVE=levelup|15|E\n",
                encoding="utf-8",
            )

            self.assertEqual(read_latest_dialog(log), "levelup")
            self.assertIsNone(read_screen_blocker(log))

    def test_dialogue_protocol_carries_source_sequence_and_pulse(self):
        active = DIALOG_ACTIVE_RE.search(
            "AUTOMATION_DIALOG_ACTIVE=checkpoint|12|E"
        )
        pulse = DIALOG_PULSE_RE.search(
            "AUTOMATION_DIALOG_PULSE=checkpoint|12|3|E"
        )
        self.assertEqual(active.groupdict(), {"source": "checkpoint", "sequence": "12"})
        self.assertEqual(
            pulse.groupdict(),
            {"source": "checkpoint", "sequence": "12", "pulse": "3"},
        )

    def test_dialogue_pulses_are_suppressed_on_special_screens(self):
        self.assertFalse(dialogue_pulse_suppressed(False, False, False, False))
        for blockers in (
            (True, False, False, False), (False, True, False, False),
            (False, False, True, False), (False, False, False, True),
        ):
            self.assertTrue(dialogue_pulse_suppressed(*blockers))

    def test_confirmed_boss_reset_can_clear_blocking_result_dialogue(self):
        reset_key = (1, 6, 7, "Cerberus (Boss)")
        self.assertTrue(
            boss_reset_dialog_recovery_allowed("interrupt", True, reset_key)
        )
        self.assertTrue(
            boss_reset_dialog_recovery_allowed("convpanel", True, reset_key)
        )
        self.assertFalse(
            boss_reset_dialog_recovery_allowed("levelup", True, reset_key)
        )
        self.assertFalse(
            boss_reset_dialog_recovery_allowed("interrupt", False, reset_key)
        )
        self.assertFalse(
            boss_reset_dialog_recovery_allowed("interrupt", True, None)
        )

    def test_convpanel_clears_stale_treasure_transition(self):
        self.assertEqual(
            clear_stale_treasure_transition("convpanel", "treasure", True),
            (None, False),
        )
        self.assertEqual(
            clear_stale_treasure_transition("checkpoint", "treasure", True),
            ("treasure", True),
        )

    def test_dialogue_click_routing_keeps_fallbacks_above_grid(self):
        controller = X11Keyboard.__new__(X11Keyboard)
        controller.layout = "deluxe"
        controller.window = 1
        controller._size = lambda _window: (800, 600)
        controller.focus = lambda: None
        clicks = []
        controller.click = lambda x, y, delay: clicks.append((x, y))

        for source in ("convpanel", "checkpoint", "interrupt"):
            controller.advance_dialog(source, 0)
        controller.advance_dialog("levelup", 0)

        self.assertEqual(clicks[:3], [(400, 261)] * 3)
        self.assertEqual(clicks[3], (400, 399))

    def test_powerup_and_purify_use_distinct_native_item_slots(self):
        controller = X11Keyboard.__new__(X11Keyboard)
        controller.layout = "deluxe"
        controller.window = 1
        controller._size = lambda _window: (800, 600)
        controller.focus = lambda: None
        clicks = []
        controller.click = lambda x, y, delay: clicks.append((x, y))

        controller.use_powerup_potion(0)
        controller.use_purification_potion(0)

        # Native inventory order is health (red), Power-Up (green), Purify
        # (blue). Guard against swapping the adjacent green and blue bottles.
        self.assertEqual(clicks, [(144, 341), (220, 341)])

    def test_incapacitation_overlay_clicks_tile_cleared_before_next_word(self):
        controller = X11Keyboard.__new__(X11Keyboard)
        controller.layout = "deluxe"
        controller.window = 1
        controller._size = lambda _window: (800, 600)
        controller.focus = lambda: None
        clicks = []
        controller.click = lambda x, y, delay: clicks.append((x, y))

        controller.dismiss_incapacitation_overlay(0)

        self.assertEqual(clicks, [(400, 480)])

    def test_clean_ready_word_skips_defensive_clear(self):
        controller = X11Keyboard.__new__(X11Keyboard)
        controller.layout = "deluxe"
        controller.window = 1
        controller._size = lambda _window: (800, 600)
        controller.focus = lambda: None
        clears = []
        clicks = []
        controller.clear_selection = lambda delay: clears.append(delay)
        controller.click = lambda x, y, delay: clicks.append((x, y))

        controller.play_word(
            "TEST/AAAA/AAAA/AAAA", "TEST", 0, 0, (0, 1, 2, 3),
            clear_first=False,
        )

        self.assertEqual(clears, [])
        self.assertEqual(len(clicks), 5)  # four tiles plus Attack

    def test_telemetry_context_uses_timer_when_deluxe_omits_chapter(self):
        state = DeluxeState(
            sequence=1, board="TEST/AAAA/AAAA/AAAA", gems=("none",) * 16,
            tile_powers=(0.0,) * 16, selectable=(True,) * 16,
            zero_damage=(False,) * 16, offense=1.0, overkill_thresholds=(),
            book=1, chapter=-1, stage=1, enemy="War Hound", hp=2,
            max_hp=2, player_hp=3, player_max_hp=3,
            treasures=(),
        )

        self.assertEqual(
            telemetry_context(state, {"current": {"book": 1, "chapter": 1}}),
            (1, 1),
        )

    def test_overlay_requires_strictly_newer_ready_sequence(self):
        self.assertFalse(ready_sequence_is_fresh(42, 42))
        self.assertFalse(ready_sequence_is_fresh(41, 42))
        self.assertTrue(ready_sequence_is_fresh(43, 42))
        self.assertTrue(ready_sequence_is_fresh(42, None))

    def test_retry_word_retains_defensive_clear(self):
        controller = X11Keyboard.__new__(X11Keyboard)
        controller.layout = "deluxe"
        controller.window = 1
        controller._size = lambda _window: (800, 600)
        controller.focus = lambda: None
        clears = []
        controller.clear_selection = lambda delay: clears.append(delay)
        controller.click = lambda x, y, delay: None

        controller.play_word(
            "TEST/AAAA/AAAA/AAAA", "TEST", 0, 0, (0, 1, 2, 3)
        )

        self.assertEqual(clears, [0])

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

    def test_sphinx_stale_board_never_falls_back_to_normal_word(self):
        normal = Candidate("WEIGHT", (0,), 4, -5, None, False, 0.9, 0)

        selected, expected = sphinx_candidate(
            "Sphinx (Riddle 1 of 5)", [normal]
        )

        self.assertIsNone(selected)
        self.assertEqual(expected, "SKY")

    def test_sphinx_last_riddle_uses_water(self):
        normal = Candidate("WANTONER", (0,), 7, -2, None, False, 1.15, 0)
        water = Candidate("WATER", (1, 2, 3), 2, -7, None, False, 0.95, 0)

        selected, mode = sphinx_candidate(
            "Sphinx (Last Riddle)", [normal, water]
        )

        self.assertIs(selected, water)
        self.assertEqual(mode, "WATER")

    def test_sphinx_incomplete_last_riddle_board_waits_for_water(self):
        normal = Candidate("WAGING", (0,), 2, -7, None, False, 0.9, 0)

        selected, expected = sphinx_candidate(
            "Sphinx (Last Riddle)", [normal]
        )

        self.assertIsNone(selected)
        self.assertEqual(expected, "WATER")

    def test_sphinx_missing_answer_allows_normal_damage_fallback(self):
        nonlethal = Candidate("WAGING", (0,), 2, -7, None, False, 0.9, 0)
        lethal = Candidate("INEBRIATED", (0,), 10, 1, None, True, 1.3, 0)

        self.assertTrue(sphinx_allows_damage_fallback(
            "Sphinx (Last Riddle)", nonlethal
        ))
        self.assertTrue(sphinx_allows_damage_fallback(
            "Sphinx (Last Riddle)", lethal
        ))
        self.assertTrue(sphinx_allows_damage_fallback(
            "Sphinx (Riddle 4 of 5)", lethal
        ))
        self.assertFalse(sphinx_allows_damage_fallback(
            "Pharaoh of Old (Boss)", lethal
        ))

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
