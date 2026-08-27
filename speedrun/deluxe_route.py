"""Route-level menu-reset decisions, separate from combat optimization."""

from __future__ import annotations

from deluxe_optimizer import DISPLAY_NAME_ALIASES, DeluxeState


def normalize_enemy(name: str) -> str:
    normalized = "".join(character for character in name.casefold() if character.isalnum())
    return DISPLAY_NAME_ALIASES.get(normalized, normalized)


# The final combat encounter in each ordinary chapter. SphinxPuzzle is omitted:
# it is a fixed-answer minigame, not a boss battle worth resetting before.
FINAL_ENCOUNTERS = frozenset({
    "polydamas", "polyphemus", "charybdis", "circe", "cerberus",
    "minotaur", "hydra", "nemeanlion", "nessus", "medusa",
    "mysteriousassassin", "thief121314", "pharoahofold",
    "dreadpiratealrobarts", "mamaroc", "miragelex", "crazymurray",
    "shaitan", "twistedvizier", "angrymob", "eternalwanderer",
    "frankenstein", "wolfman", "thecreature", "grim",
    "fallenwizardhero", "themummy", "dracula", "codex",
})

# Penultimate roster entries from bwakit/game/data/enemy_rosters.txt.  Reset
# after these enemies are confirmed defeated, before the boss entrance begins.
# Hydra and Codex chapters contain no ordinary predecessor encounter.
PRE_BOSS_ENCOUNTERS = frozenset({
    "alexander", "cyclopswarrior", "scylla", "enchantedserpent", "orthrus",
    "harpywitch", "stymphalianbirdsteel", "naiad", "greaterbasilisk",
    "firebreather", "thief91011", "embalmedguardian", "swashbuckler",
    "bullelephant", "miragegoat", "flyingarmor", "airspirit", "necromancer",
    "hatefulhousemaid", "plaguedpork", "arnoldstein", "werehawk", "mrblobs",
    "disturbedskeleton", "fallenhuntresshero", "unlivingpyromancer",
    "vampirecultist",
})


# Exceptional resets from the WR notes. These happen after the named enemy;
# the normal boss-entry rule below covers every repeated "exit before boss"
# note without duplicating it chapter by chapter.
RESET_AFTER = frozenset({
    (1, 2, "cyclopsherder"),
    (1, 8, "caledonianboar"),
    (1, 10, "enyo"),
    (2, 5, "bilgedog"),
    (2, 6, "elephant"),
    (2, 7, "miragetrojan"),
    (3, 1, "maliciousmagistrate"),
    (3, 3, "connystein"),
    (3, 6, "graverobber"),
    (3, 8, "unlivingarcher"),
})


def encounter_key(state: DeluxeState) -> tuple[int, int, int, str]:
    return (state.book, state.chapter, state.stage, normalize_enemy(state.enemy))


def is_boss_encounter(state: DeluxeState) -> bool:
    normalized = normalize_enemy(state.enemy)
    return (
        "(boss)" in state.enemy.casefold()
        or normalized in FINAL_ENCOUNTERS
        or normalized.startswith("hydrahead")
        or normalized == "hydramainhead"
    )


def menu_reset_reason(
    state: DeluxeState,
    previous_enemy: DeluxeState | None,
    already_reset: set[tuple[int, int, int, str]],
) -> str | None:
    """Return why the current READY encounter should reset, at most once."""
    key = encounter_key(state)
    if key in already_reset:
        return None
    return None


def post_victory_reset_reason(
    defeated: DeluxeState | None,
    already_reset: set[tuple[int, int, int, str]],
    chapter_override: int | None = None,
) -> str | None:
    """Return a reset reason immediately after a defeated encounter."""
    if defeated is None or encounter_key(defeated) in already_reset:
        return None
    enemy = normalize_enemy(defeated.enemy)
    live_chapter = (
        defeated.chapter if defeated.chapter >= 1 else chapter_override
    )
    special_key = (defeated.book, live_chapter, enemy)
    if special_key in RESET_AFTER:
        return f"after route checkpoint {defeated.enemy}"
    if enemy in PRE_BOSS_ENCOUNTERS:
        return f"after {defeated.enemy}, before boss entrance"
    return None
