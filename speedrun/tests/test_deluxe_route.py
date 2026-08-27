import unittest

from deluxe_optimizer import DeluxeState
from deluxe_route import (
    encounter_key, is_boss_encounter, menu_reset_reason,
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
