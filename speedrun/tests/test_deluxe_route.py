import unittest

from deluxe_optimizer import DeluxeState
from deluxe_route import (
    encounter_key, is_boss_encounter, is_chapter_boss_defeat, menu_reset_reason,
    post_victory_reset_reason,
)


def state(**overrides):
    values = dict(
        sequence=1, board="AAAA/AAAA/AAAA/AAAA", gems=("none",) * 16,
        tile_powers=(0.0,) * 16, book=1, chapter=2, stage=1,
        enemy="Mountain Goat", hp=3, max_hp=3, offense=0,
        treasures=frozenset(), overkill_thresholds=(),
    )
    values.update(overrides)
    return DeluxeState(**values)


class DeluxeRouteTests(unittest.TestCase):
    def test_display_name_alias_matches_penultimate_roster_entry(self):
        enemy_state = state(enemy="Steel Stymphalian")
        self.assertEqual(
            post_victory_reset_reason(enemy_state, set()),
            "after Steel Stymphalian, before boss entrance",
        )

    def test_all_chapter_bosses_use_generic_rule(self):
        self.assertTrue(is_boss_encounter(state(enemy="Polyphemus (Boss)")))
        self.assertTrue(is_boss_encounter(state(enemy="Circe", chapter=4)))
        self.assertTrue(is_boss_encounter(state(enemy="Hydra (Head 1)", chapter=7)))

    def test_sphinx_is_not_treated_as_boss(self):
        self.assertFalse(is_boss_encounter(
            state(book=2, chapter=4, enemy="Sphinx (Riddle 1 of 5)")
        ))

    def test_ali_baba_reset_uses_penultimate_thief_group(self):
        penultimate = state(book=2, chapter=2, enemy="Thieves 9, 10 & 11")
        earlier = state(book=2, chapter=2, enemy="Thieves 6, 7 & 8")

        self.assertIsNotNone(post_victory_reset_reason(penultimate, set()))
        self.assertIsNone(post_victory_reset_reason(earlier, set()))

    def test_ali_baba_live_final_boss_name_matches_roster(self):
        boss = state(
            book=2, chapter=2, enemy="Thieves 12, 13 & 14 (Boss)"
        )

        self.assertTrue(is_boss_encounter(boss))

    def test_dread_pirate_skip_triggers_after_swashbuckler(self):
        predecessor = state(
            book=2, chapter=5, enemy="Swashbuckler", hp=0, max_hp=24
        )

        self.assertEqual(
            post_victory_reset_reason(predecessor, set()),
            "after Swashbuckler, before boss entrance",
        )

    def test_late_chapter_boss_event_does_not_restart_next_chapter(self):
        defeated = state(enemy="Polyphemus (Boss)", stage=6)

        self.assertTrue(is_chapter_boss_defeat(defeated))
        self.assertIsNone(post_victory_reset_reason(defeated, set()))

    def test_hydra_only_resets_after_main_head(self):
        head = state(enemy="Hydra (Head 6)", chapter=7)
        main = state(enemy="Hydra (Main Head)", chapter=7)

        self.assertFalse(is_chapter_boss_defeat(head))
        self.assertIsNone(post_victory_reset_reason(head, set()))
        self.assertTrue(is_chapter_boss_defeat(main))
        self.assertIsNone(post_victory_reset_reason(main, set()))

    def test_midchapter_note_triggers_immediately_after_defeat(self):
        defeated = state(enemy="Cyclops Herder", stage=3)

        self.assertEqual(
            post_victory_reset_reason(defeated, set()),
            "after route checkpoint Cyclops Herder",
        )

    def test_midchapter_note_uses_inferred_chapter_when_lua_omits_it(self):
        defeated = state(chapter=-1, enemy="Calydonian Boar", stage=3)

        self.assertEqual(
            post_victory_reset_reason(defeated, set(), chapter_override=8),
            "after route checkpoint Calydonian Boar",
        )

    def test_unique_route_enemy_survives_stale_inferred_chapter(self):
        defeated = state(chapter=-1, enemy="Enyo", stage=3)

        self.assertEqual(
            post_victory_reset_reason(defeated, set(), chapter_override=9),
            "after route checkpoint Enyo",
        )

    def test_predecessor_triggers_before_boss_ready(self):
        defeated = state(enemy="Cyclops Warrior", stage=5)

        self.assertEqual(
            post_victory_reset_reason(defeated, set()),
            "after Cyclops Warrior, before boss entrance",
        )

    def test_boss_ready_no_longer_triggers_reset(self):
        boss = state(enemy="Polyphemus (Boss)", stage=6)

        self.assertIsNone(menu_reset_reason(boss, None, set()))

    def test_encounter_resets_only_once(self):
        defeated = state(enemy="Cyclops Warrior", stage=5)
        completed = {encounter_key(defeated)}

        self.assertIsNone(post_victory_reset_reason(defeated, completed))


if __name__ == "__main__":
    unittest.main()
