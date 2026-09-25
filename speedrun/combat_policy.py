"""Combat decisions (potions, boss finishers, riddles), without input or log I/O."""

from __future__ import annotations

from combat_models import Candidate, DeluxeState
from deluxe_route import is_boss_encounter


SPHINX_ANSWERS = {
    "Sphinx (Riddle 1 of 5)": "SKY",
    "Sphinx (Riddle 2 of 5)": "WALL",
    "Sphinx (Riddle 3 of 5)": "FIST",
    "Sphinx (Riddle 4 of 5)": "TRUTH",
    "Sphinx (Last Riddle)": "WATER",
}


def is_book3_final_gauntlet(state: DeluxeState) -> bool:
    """Recognize Chapter 10 even when Deluxe omits its chapter number."""
    return state.book == 3 and (
        state.chapter == 10 or state.enemy.startswith("Summoned ")
    )


def should_use_health_potion(
    state: DeluxeState, candidate: Candidate | None = None
) -> bool:
    """Heal before attacking when Lex has at most four hearts.

    Hydra and the Book 3 final gauntlet retain their conservative full-heal
    rules because leaving either sequence discards substantially more progress.
    Ordinary encounters refill Lex between enemies, so do not spend a potion
    before a predicted killing blow. High-risk multi-phase encounters retain
    their conservative rules below.
    """
    if state.player_hp < 0 or state.player_max_hp <= 0:
        return False
    if not state.health_potion_available:
        return False
    in_danger = (
        state.player_hp <= min(4.0, state.player_max_hp)
        and state.player_hp < state.player_max_hp
    )
    if state.player_petrified:
        return state.player_hp < state.player_max_hp
    if (state.player_stunned or state.player_frozen) and in_danger:
        return True
    if state.enemy in SPHINX_ANSWERS and in_danger:
        return True
    if state.enemy.startswith("Hydra (") or is_book3_final_gauntlet(state):
        return state.player_hp < state.player_max_hp
    planned_finisher = bool(
        candidate is not None
        and (
            candidate.lethal
            or (
                state.attack_potion_available
                and candidate.damage * 1.25 >= state.hp
            )
        )
    )
    return in_danger and not planned_finisher


def health_potion_confirmed(before: DeluxeState, after: DeluxeState) -> bool:
    """Return whether native state proves the requested potion took effect."""
    return not after.health_potion_available or after.player_hp > before.player_hp


def incapacitation_recovery_action(
    *, purify_available: bool, health_available: bool,
    player_hp: float, player_max_hp: float,
) -> str:
    """Choose the safe, ordered response to a confirmed lost-turn status."""
    if purify_available:
        return "purify"
    if (
        health_available and 0 < player_hp <= min(4.0, player_max_hp)
        and player_hp < player_max_hp
    ):
        return "heal_then_continue"
    return "continue"


def should_use_powerup_potion(
    state: DeluxeState, candidate: Candidate | None,
) -> bool:
    """Spend Power-Up when its native 1.25x boost removes a whole turn.

    Enemy Power Down is a DamageMultiplierEffect below 1.0. Candidate damage
    is the un-debuffed engine value, so a nominally lethal word is not actually
    lethal while that status remains; the potion replaces/counters it with the
    positive multiplier.
    """
    return bool(
        candidate is not None
        and state.attack_potion_available
        and not state.player_powered_up
        and candidate.damage * state.player_damage_multiplier < state.hp
        and candidate.damage * 1.25 >= state.hp
    )


def should_use_purification_potion(
    state: DeluxeState, candidate: Candidate | None = None,
) -> bool:
    """Cleanse blocking ailments without wasting Purify on a finisher."""
    if state.player_petrified:
        return True
    if (
        state.enemy.startswith("Hydra (")
        and state.player_has_damage_over_time
    ):
        # Hydra chains three heads without an ordinary encounter reset. Cleanse
        # the live status even when the current word is lethal so it cannot
        # carry into the final-head transition.
        return True
    if candidate is not None and candidate.lethal:
        return False
    if state.player_has_damage_over_time:
        return True
    return False


def boss_finish_strategy(
    state: DeluxeState, strategy: str, ranked: list[Candidate]
) -> str:
    """Avoid valueless overkill animations on a boss's finishing turn."""
    if not any(candidate.lethal for candidate in ranked):
        return strategy
    if state.enemy.startswith("Hydra ("):
        # Each head awards nothing for excess damage, while Lex still spends
        # time playing the larger overkill response before the next head.
        return "minimum-overkill"
    if is_boss_encounter(state):
        return "shortest-lethal"
    return strategy


def sphinx_candidate(
    enemy: str, ranked: list[Candidate]
) -> tuple[Candidate | None, str | None]:
    """Return the fixed answer required by a Sphinx riddle."""
    answer = SPHINX_ANSWERS.get(enemy)
    if answer is None:
        return None, None
    return next((candidate for candidate in ranked if candidate.word == answer), None), answer


def sphinx_allows_damage_fallback(enemy: str, candidate: Candidate) -> bool:
    """Use ordinary combat when a Sphinx answer is absent from the board."""
    return enemy in SPHINX_ANSWERS

