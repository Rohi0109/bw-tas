"""Route-level menu-reset decisions, separate from combat optimization."""

from __future__ import annotations

from deluxe_optimizer import DeluxeState


def normalize_enemy(name: str) -> str:
    return "".join(character for character in name.casefold() if character.isalnum())


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


# Exceptional resets from the WR notes. These happen after the named enemy;
# the normal boss-entry rule below covers every repeated "exit before boss"
# note without duplicating it chapter by chapter.
RESET_AFTER = frozenset({
    (1, 2, "cyclopsherder"),
    (1, 8, "calydonianboar"),
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
    if previous_enemy is not None and previous_enemy.enemy != state.enemy:
        previous_key = (
            previous_enemy.book,
            previous_enemy.chapter,
            normalize_enemy(previous_enemy.enemy),
        )
        if previous_key in RESET_AFTER:
            return f"after {previous_enemy.enemy}"
    if is_boss_encounter(state):
        return f"before boss {state.enemy}"
    return None
