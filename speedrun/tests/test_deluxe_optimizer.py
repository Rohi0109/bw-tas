import unittest

from deluxe_optimizer import (
    DeluxeState, candidates, ceil_quarter, choose, damage_for,
    load_chapter1_hp_map, parse_state, powerup_lethal_candidate,
    validate_chapter1_state,
)


def state(**overrides):
    values = dict(
        sequence=1,
        board="AAAA/AAAA/AAAA/AAAA",
        gems=("none",) * 16,
        tile_powers=(0.0,) * 16,
        book=1,
        chapter=1,
        stage=1,
        enemy="Trojan Spearman",
        hp=1.0,
        max_hp=1.0,
        offense=0.0,
        treasures=frozenset(),
        overkill_thresholds=(1.95, 3.0, 5.0, 8.0, 11.0, 15.0, 20.0),
    )
    values.update(overrides)
    return DeluxeState(**values)


class DeluxeOptimizerTests(unittest.TestCase):
    def test_decorated_enemy_names_match_roster(self):
        hp_map = {
            "mountaingoat": 3,
            "polyphemus": 7,
            "hydra": (4, 4, 4, 4, 5, 5, 7),
            "caledonianboar": 14,
            "stymphalianbirdbronze": 15,
            "stymphalianbirdsteel": 16,
            "centaurwarrior": 17,
            "centaurarcher": 18,
            "helead": 18,
            "basilisk": 25,
        }
        goat = state(enemy="Angry Mountain Goat", max_hp=3)
        boss = state(enemy="Polyphemus (Boss)", max_hp=7)

        self.assertIsNone(validate_chapter1_state(goat, hp_map))
        self.assertIsNone(validate_chapter1_state(boss, hp_map))
        for head, hp in enumerate((4, 4, 4, 4, 5, 5, 7), 1):
            hydra = state(enemy=f"Hydra (Head {head})", max_hp=hp)
            self.assertIsNone(validate_chapter1_state(hydra, hp_map))
        main_head = state(enemy="Hydra (Main Head)", max_hp=7)
        self.assertIsNone(validate_chapter1_state(main_head, hp_map))
        boar = state(enemy="Calydonian Boar", max_hp=14)
        self.assertIsNone(validate_chapter1_state(boar, hp_map))
        bronze = state(enemy="Bronze Stymphalian", max_hp=15)
        steel = state(enemy="Steel Stymphalian", max_hp=16)
        self.assertIsNone(validate_chapter1_state(bronze, hp_map))
        self.assertIsNone(validate_chapter1_state(steel, hp_map))
        for display, hp in (
            ("Centaur Grappler", 17),
            ("Centaur Hunter", 18),
            ("Limniad", 18),
            ("Lesser Basilisk", 25),
        ):
            self.assertIsNone(validate_chapter1_state(
                state(enemy=display, max_hp=hp), hp_map
            ))

    def test_metal_bonus_snapshot_is_not_counted_as_gem(self):
        log = "\n".join([
            "AUTOMATION_LETTERS=8|0|METL|E",
            "AUTOMATION_LETTERS=8|1|AAAA|E",
            "AUTOMATION_LETTERS=8|2|AAAA|E",
            "AUTOMATION_LETTERS=8|3|AAAA|E",
            "AUTOMATION_GEMS=8|0|m,n,n,n|E",
            "AUTOMATION_GEMS=8|1|n,n,n,n|E",
            "AUTOMATION_GEMS=8|2|n,n,n,n|E",
            "AUTOMATION_GEMS=8|3|n,n,n,n|E",
            "AUTOMATION_POWERS=8|0|0.1875,0,0,0|E",
            "AUTOMATION_POWERS=8|1|0,0,0,0|E",
            "AUTOMATION_POWERS=8|2|0,0,0,0|E",
            "AUTOMATION_POWERS=8|3|0,0,0,0|E",
            "AUTOMATION_MODS=8|none|E",
            "AUTOMATION_OVERKILL=8|1.95,3,5,8,11,15,20|E",
            "AUTOMATION_CONTEXT=8|1|1|1|E",
            "AUTOMATION_ENEMY=8|Griffon|E",
            "AUTOMATION_HEALTH=8|7|7|0|E",
            "AUTOMATION_READY_SEQ=8|E",
        ])
        parsed = parse_state(log)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.gems[0], "metal")
        metal = next(candidate for candidate in candidates(parsed, ["MET"], frozenset(), 0.06))
        self.assertEqual(metal.gem_count, 0)

    def test_unknown_bonus_code_is_preserved_without_becoming_a_gem(self):
        log = "\n".join([
            "AUTOMATION_LETTERS=9|0|USED|E",
            "AUTOMATION_LETTERS=9|1|AAAA|E",
            "AUTOMATION_LETTERS=9|2|AAAA|E",
            "AUTOMATION_LETTERS=9|3|AAAA|E",
            "AUTOMATION_GEMS=9|0|u,n,n,n|E",
            "AUTOMATION_GEMS=9|1|n,n,n,n|E",
            "AUTOMATION_GEMS=9|2|n,n,n,n|E",
            "AUTOMATION_GEMS=9|3|n,n,n,n|E",
            "AUTOMATION_POWERS=9|0|0.25,0,0,0|E",
            "AUTOMATION_POWERS=9|1|0,0,0,0|E",
            "AUTOMATION_POWERS=9|2|0,0,0,0|E",
            "AUTOMATION_POWERS=9|3|0,0,0,0|E",
            "AUTOMATION_MODS=9|none|E",
            "AUTOMATION_OVERKILL=9|1.95,3,5,8,11,15,20|E",
            "AUTOMATION_CONTEXT=9|1|1|1|E",
            "AUTOMATION_ENEMY=9|Griffon|E",
            "AUTOMATION_HEALTH=9|7|7|0|E",
            "AUTOMATION_READY_SEQ=9|E",
        ])
        parsed = parse_state(log)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.gems[0], "bonus-u")
        used = next(candidate for candidate in candidates(parsed, ["USED"], frozenset(), 0.06))
        self.assertEqual(used.gem_count, 0)

    def test_parse_complete_state(self):
        line = "noise AUTOMATION_CONTEXT=7|1|2|3|E\n"
        line += "AUTOMATION_ENEMY=7|Trojan Warrior|E\n"
        line += "AUTOMATION_HEALTH=7|2|2|0.125|E\n"
        for row, letters in enumerate(("ABCD", "EFGH", "IJKL", "MNOP")):
            line += f"AUTOMATION_LETTERS=7|{row}|{letters}|E\n"
            line += f"AUTOMATION_GEMS=7|{row}|n,n,n,n|E\n"
            line += f"AUTOMATION_POWERS=7|{row}|0,0,0,0|E\n"
        line += "AUTOMATION_MODS=7|Artemis Bow|E\n"
        line += "AUTOMATION_ITEMS=7|3|1.25|E\n"
        line += "AUTOMATION_OVERKILL=7|1.95,3,5,8,11,15,20|E\n"
        line += "AUTOMATION_READY_SEQ=7|E\n"
        parsed = parse_state(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.sequence, 7)
        self.assertEqual(parsed.enemy, "Trojan Warrior")
        self.assertEqual(parsed.treasures, frozenset({"artemis bow"}))
        self.assertEqual(parsed.powerup_potions, 3)
        self.assertEqual(parsed.attack_multiplier, 1.25)

    def test_quarter_rounding(self):
        self.assertEqual(ceil_quarter(0.01), 0.25)
        self.assertEqual(ceil_quarter(0.25), 0.25)
        self.assertEqual(ceil_quarter(0.26), 0.5)

    def test_hand_and_metal_damage(self):
        current = state(treasures=frozenset({"hand of hercules"}))
        # Three letters: .25 base, metal multiplier, then +1 heart, rounded.
        self.assertEqual(
            damage_for(current, "AAA", (0, 1, 2), frozenset({"AAA"})),
            1.5,
        )

    def test_active_powerup_multiplier_is_applied(self):
        current = state(attack_multiplier=1.25)

        self.assertEqual(
            damage_for(current, "AAAAAAAA", tuple(range(8)), frozenset()),
            2.5,
        )

    def test_powerup_is_suggested_only_when_it_makes_attack_lethal(self):
        current = state(hp=0.5, powerup_potions=1)
        ranked = candidates(current, ["AAA"], frozenset(), 0.1)

        powered = powerup_lethal_candidate(ranked)

        self.assertIsNotNone(powered)
        self.assertEqual(powered.word, "AAA")
        self.assertEqual(powered.damage, 0.5)

    def test_powerup_is_not_suggested_when_normal_attack_is_lethal(self):
        current = state(hp=0.25, powerup_potions=1)
        ranked = candidates(current, ["AAA"], frozenset(), 0.1)

        self.assertIsNone(powerup_lethal_candidate(ranked))

    def test_wooden_parrot_uses_live_r_tile_power_once(self):
        # The Lua hook runs R through the game's LETTER_BONUSES/ApplyBonus
        # calculation. Wooden Parrot's extra letter value arrives as tile
        # power, so the optimizer consumes it once instead of reapplying it.
        powers = (1.0, 0.0, 1.0) + (0.0,) * 13
        current = state(
            tile_powers=powers,
            treasures=frozenset({"wooden parrot"}),
        )

        self.assertEqual(
            damage_for(current, "RAR", (0, 1, 2), frozenset()),
            2.25,
        )

    def test_wooden_parrot_does_not_bonus_words_without_r(self):
        current = state(treasures=frozenset({"wooden parrot"}))

        self.assertEqual(
            damage_for(current, "AAA", (0, 1, 2), frozenset()),
            0.25,
        )

    def test_duplicate_letter_uses_stronger_gem_tile(self):
        powers = (0.0,) * 15 + (1.0,)
        current = state(tile_powers=powers, gems=("none",) * 15 + ("diamond",))
        ranked = candidates(current, ["AAA"], frozenset(), 0.1)
        self.assertIn(15, ranked[0].path)

    def test_overkill_strategy_prefers_tier_then_speed(self):
        current = state(hp=0.25)
        ranked = candidates(current, ["AAA", "AAAAAAAAAAAA"], frozenset(), 0.1)
        selected, alternatives = choose(ranked, "overkill-tier")
        self.assertEqual(selected.word, "AAAAAAAAAAAA")
        self.assertEqual(alternatives["shortest_lethal"].word, "AAA")

    def test_chapter1_hp_map_does_not_shift_after_hydra(self):
        hp = load_chapter1_hp_map()
        self.assertEqual(hp["hydra"], (4, 4, 4, 4, 5, 5, 7))
        self.assertEqual(hp["medusa"], 30)


if __name__ == "__main__":
    unittest.main()
