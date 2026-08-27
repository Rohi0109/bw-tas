import unittest

from deluxe_optimizer import DeluxeState
from deluxe_route import encounter_key, is_boss_encounter, menu_reset_reason


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
    def test_all_chapter_bosses_use_generic_rule(self):
        self.assertTrue(is_boss_encounter(state(enemy="Polyphemus (Boss)")))
        self.assertTrue(is_boss_encounter(state(enemy="Circe", chapter=4)))
        self.assertTrue(is_boss_encounter(state(enemy="Hydra (Head 1)", chapter=7)))

    def test_sphinx_is_not_treated_as_boss(self):
        self.assertFalse(is_boss_encounter(
            state(book=2, chapter=4, enemy="Sphinx (Riddle 1 of 5)")
        ))

    def test_midchapter_note_triggers_on_next_enemy(self):
        previous = state(enemy="Cyclops Herder", stage=3)
        current = state(enemy="Angry Ram", stage=4)

        self.assertEqual(menu_reset_reason(current, previous, set()),
                         "after Cyclops Herder")

    def test_encounter_resets_only_once(self):
        boss = state(enemy="Polyphemus (Boss)", stage=6)
        completed = {encounter_key(boss)}

        self.assertIsNone(menu_reset_reason(boss, None, completed))


if __name__ == "__main__":
    unittest.main()
