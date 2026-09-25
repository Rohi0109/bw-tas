"""Route-level menu-reset decisions, separate from combat optimization."""

from __future__ import annotations

from combat_models import DeluxeState
from deluxe_optimizer import DISPLAY_NAME_ALIASES


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
RESET_AFTER_ENEMY = frozenset((book, enemy) for book, _, enemy in RESET_AFTER)

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


def is_chapter_boss_defeat(state: DeluxeState) -> bool:
    """Return whether this defeat finishes a chapter's boss encounter."""
    normalized_name = "".join(
        character for character in state.enemy.casefold() if character.isalnum()
    )
    if normalized_name.startswith("hydrahead"):
        return False
    if normalized_name == "hydramainhead":
        return True
    return (
        "(boss)" in state.enemy.casefold()
        or normalize_enemy(state.enemy) in FINAL_ENCOUNTERS
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
    if special_key in RESET_AFTER or (defeated.book, enemy) in RESET_AFTER_ENEMY:
        return f"after route checkpoint {defeated.enemy}"
    if enemy in PRE_BOSS_ENCOUNTERS:
        return f"after {defeated.enemy}, before boss entrance"
    # Multi-phase encounters do not expose the ordinary save-ready death edge.
    # Once DEFEATED identifies their completed phase, use the same menu skip
    # instead of carrying the old sparse checkpoint-only route.
    # Head 5 -> Head 6 is a delayed in-memory handoff. Leaving here repeatedly
    # reloads Head 5's transition state and can spend several seconds clicking
    # Adventure before Head 6 finally becomes authoritative. Let this single
    # phase advance normally; the other proven Hydra exits remain enabled.
    if enemy == "hydrahead5":
        return None
    if enemy.startswith("hydrahead"):
        return f"after {defeated.enemy}"
    # Sphinx boards are one continuous puzzle and must retain their rotation.
    if enemy.startswith("sphinx"):
        return None
    # DEFEATED is the first edge that proves encounter progress was committed;
    # animation-complete/RESET_READY can still reload the dead enemy.
    if enemy != "codex":
        return f"after {defeated.enemy}"
    return None
