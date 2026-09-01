"""Continuously solve boards emitted by the Lua automation hook."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import replace
from pathlib import Path

from live_runner import X11Keyboard, best_word
from deluxe_optimizer import (
    Candidate, DeluxeState, candidates, choose, load_chapter1_hp_map,
    load_metal_words, parse_state, strategy_for_state, validate_chapter1_state,
)
from book1_optimizer import (
    TELEMETRY_SCHEMA_VERSION, DecisionOverrides, TransitionCorpus, candidate_payload,
    choose_recorded_lookahead, pareto_candidates, state_fingerprint,
    state_payload,
)
from deluxe_route import (
    encounter_key, is_boss_encounter, is_chapter_boss_defeat,
    post_victory_reset_reason,
)
from menu_runner import MenuTiming, reset_from_battle
from run_timer import (
    DEFAULT_STATE as DEFAULT_TIMER_STATE,
    load_state as load_timer_state,
    mark_current_issue,
    process_line as process_timer_line,
    save_run_history,
    save_state as save_timer_state,
    update_tas_best,
)


BOARD_PREFIX = "AUTOMATION_BOARD="
READY_PREFIX = "AUTOMATION_READY="
BOARD_EVENT_RE = re.compile(
    r"AUTOMATION_(?P<kind>BOARD|READY)="
    r"(?P<board>[A-Z]{4}/[A-Z]{4}/[A-Z]{4}/[A-Z]{4})"
)
DONE_MARKER = "no more enemies left"
CHAPTER_RE = re.compile(
    r"Book:StartGame called for book (?P<book>[^,]+), chapter (?P<chapter>\d+)"
)
DIALOG_ACTIVE_RE = re.compile(
    r"AUTOMATION_DIALOG_ACTIVE=(?P<source>[a-z]+)\|(?P<sequence>\d+)\|E"
)
DIALOG_PULSE_RE = re.compile(
    r"AUTOMATION_DIALOG_PULSE=(?P<source>[a-z]+)\|(?P<sequence>\d+)\|"
    r"(?P<pulse>\d+)\|E"
)
DIALOG_INACTIVE_RE = re.compile(r"AUTOMATION_DIALOG_INACTIVE=(?P<sequence>\d+)\|E")
PLAY_TUTORIAL_RE = re.compile(r"AUTOMATION_PLAY_TUTORIAL=(?P<sequence>\d+)\|E")
LEGACY_SCREEN_RE = re.compile(
    r"AUTOMATION_DIALOG=(?P<kind>treasure|none)\|(?P<sequence>\d+)\|E"
)
DEFEATED_RE = re.compile(r"AUTOMATION_DEFEATED=(?P<enemy>[^|]+)\|E")
ZERO_HEALTH_RE = re.compile(r"AUTOMATION_ZERO_HEALTH=(?P<enemy>[^|]+)\|E")
ATTACK_SUBMITTED_RE = re.compile(
    r"AUTOMATION_ATTACK_SUBMITTED=(?P<enemy>[^|]+)\|E"
)
RESET_READY_RE = re.compile(
    r"AUTOMATION_BOSS_RESET_READY=(?P<enemy>[^|]+)\|E"
)
PLAYER_STUNNED_RE = re.compile(
    r"AUTOMATION_PLAYER_(?P<kind>STUNNED|FROZEN|PETRIFIED)=(?P<active>[01])"
    r"(?:\|(?P<hp>-?\d+(?:\.\d+)?)\|(?P<max_hp>-?\d+(?:\.\d+)?)"
    r"\|(?P<health_potion>[01])(?:\|(?P<purify_potion>[01]))?)?\|E"
)
INCAP_OVERLAY_RE = re.compile(
    r"AUTOMATION_INCAP_OVERLAY=(?P<kind>stunned|frozen|petrified)\|"
    r"(?P<frame>[^|]+)"
    r"(?:\|(?P<hp>-?\d+(?:\.\d+)?)\|(?P<max_hp>-?\d+(?:\.\d+)?)"
    r"\|(?P<health_potion>[01])\|(?P<purify_potion>[01]))?\|E"
)
CHAPTER_MAP_RE = re.compile(
    r"AUTOMATION_CHAPTER_MAP=(?P<book>nil|\d+)\|"
    r"(?P<current>nil|\d+)\|(?P<chapter>nil|\d+)\|"
    r"(?P<selected>-?\d+)\|(?P<enabled>true|false)\|E"
)
CHAPTER_ACTION_RE = re.compile(
    r"AUTOMATION_CHAPTER_ACTION=(?P<action>[a-z-]+)\|E"
)
LUA_WAIT_MARKER = "Program in waiting. Type go() or press F5 to continue execution."
TREASURE_CONTEXT_RE = re.compile(
    r"AUTOMATION_TREASURE_CONTEXT=(?P<book>nil|\d+)\|"
    r"(?P<current>nil|\d+)\|(?P<selected>-?\d+)\|E"
)
MINIGAME_PROMPT_RE = re.compile(
    r"AUTOMATION_MINIGAME_PROMPT=(?P<book>nil|\d+)\|"
    r"(?P<chapter>-?\d+)\|(?P<sequence>\d+)\|E"
)
SPHINX_ANSWERS = {
    "Sphinx (Riddle 1 of 5)": "SKY",
    "Sphinx (Riddle 2 of 5)": "WALL",
    "Sphinx (Riddle 3 of 5)": "FIST",
    "Sphinx (Riddle 4 of 5)": "TRUTH",
    "Sphinx (Last Riddle)": "WATER",
}
TUTORIAL_PLAY_BOARD = "SFAE/PFUN/RJDY/TLIS"
TREASURE_LOADOUT_AFTER_BOSS = {
    "Circe (Boss)": (0, 2, 3),       # Bow, Golden Fleece, Icarus Sandals
    "Cerberus (Boss)": (0, 3, 6),    # Bow, Icarus Sandals, Heph's Hammer
    "Minotaur (Boss)": (0, 3, 6),    # Bow, Boots of Theseus, Heph's Hammer
    "Hydra (Boss)": (0, 3, 6),       # Arch, Boots, Wooden Parrot upgrades
    "Maladin (Boss)": (0, 6, 10),    # Arch, Hand, Wooden Parrot
}

PURIFY_AFTER_HIT_ENEMIES = frozenset({
    "Lesser Basilisk", "Greater Basilisk", "Medusa (Boss)",
})


def treasure_slots_after(enemy: str) -> tuple[int, ...] | None:
    """Resolve multi-phase boss display names to their treasure route."""
    route_enemy = "Hydra (Boss)" if enemy.startswith("Hydra (Head ") else enemy
    return TREASURE_LOADOUT_AFTER_BOSS.get(route_enemy)


def clear_stale_treasure_transition(
    source: str, blocked_screen: str | None, selection_started: bool,
) -> tuple[str | None, bool]:
    """Let a native conversation supersede a stale treasure-screen marker.

    Deluxe can publish its legacy treasure edge before the post-boss Cassandra
    conversation becomes active. Once ``convpanel.Active()`` is true, the
    visible screen is authoritatively a conversation and treasure clicks must
    no longer suppress its Lua-authorized pulses.
    """
    if source == "convpanel":
        return None, False
    return blocked_screen, selection_started


def clear_stale_treasure_on_ready(
    blocked_screen: str | None, selection_started: bool,
) -> tuple[str | None, bool]:
    """Treat native combat READY as proof the treasure transition is over."""
    return None, False


def telemetry_context(
    state: DeluxeState, timer_state: dict | None,
) -> tuple[int, int]:
    """Recover the chapter omitted by Deluxe and freeze it at submission.

    Most native Deluxe snapshots report chapter ``-1``. The persistent timer
    has already resolved the chapter from the enemy roster, and must be read
    when input is submitted (not when the next enemy arrives).
    """
    if state.book >= 1 and state.chapter >= 1:
        return state.book, state.chapter
    current = timer_state.get("current") if timer_state is not None else None
    if current is not None:
        return int(current["book"]), int(current["chapter"])
    return state.book, state.chapter


def ready_sequence_is_fresh(sequence: int, required_after: int | None) -> bool:
    """Only a later native rack may reclaim input after an overlay."""
    return required_after is None or sequence > required_after


def lua_runtime_is_waiting(text: str) -> bool:
    """Recognize the debugger pause emitted by the embedded Lua runtime."""
    marker_at = text.rfind(LUA_WAIT_MARKER)
    if marker_at < 0:
        return False
    suffix = text[marker_at + len(LUA_WAIT_MARKER):]
    return not suffix.strip("\x00\b >\r\n\t")


def state_is_incapacitated(state: DeluxeState | None) -> bool:
    """Recover an active native overlay when the runner attaches mid-effect."""
    return bool(
        state is not None
        and (state.player_stunned or state.player_frozen or state.player_petrified)
    )


def latest_incapacitation_state(
    text: str, state: DeluxeState | None = None,
) -> bool:
    """Replay post-snapshot incap edges when attaching to an existing log."""
    active = {
        "stunned": bool(state is not None and state.player_stunned),
        "frozen": bool(state is not None and state.player_frozen),
        "petrified": bool(state is not None and state.player_petrified),
    }
    for event in PLAYER_STUNNED_RE.finditer(text):
        active[event.group("kind").casefold()] = event.group("active") == "1"
    return any(active.values())


def latest_active_incapacitation_event(text: str):
    """Return the latest telemetry edge for a status that remains active."""
    active_events = {"stunned": None, "frozen": None, "petrified": None}
    for event in PLAYER_STUNNED_RE.finditer(text):
        kind = event.group("kind").casefold()
        active_events[kind] = event if event.group("active") == "1" else None
    remaining = [event for event in active_events.values() if event is not None]
    return max(remaining, key=lambda event: event.start(), default=None)


def latest_unresolved_incapacitation_overlay(text: str):
    """Recover an overlay frame emitted after the latest actionable READY."""
    overlays = list(INCAP_OVERLAY_RE.finditer(text))
    if not overlays:
        return None
    latest = overlays[-1]
    return latest if latest.start() > text.rfind("AUTOMATION_READY_SEQ=") else None


def treasure_slots_for_state(state: DeluxeState) -> tuple[int, ...] | None:
    """Choose the route loadout for a treasure screen after this state."""
    slots = treasure_slots_after(state.enemy)
    if slots is not None:
        return slots
    if state.book == 1:
        # A loadout room can also appear after a non-boss checkpoint. Preserve
        # the already validated Book 1 route instead of waiting for a boss name.
        if "heph's hammer" in state.treasures:
            return (0, 3, 6)
        if "icarus sandals" in state.treasures:
            return (0, 2, 3)
    if state.book == 3:
        # Book 3 repeatedly asks for a loadout at chapter entry. Keep the
        # validated Arch of Xyzzy + Hand of Hercules + Wooden Parrot route even
        # when the chapter-map transition has replaced the submitted boss.
        return (0, 6, 10)
    return None


def treasure_slots_for_context(book: int, selected_chapter: int) -> tuple[int, ...] | None:
    """Recover the validated loadout when the runner starts in Treasure Room."""
    if book == 1:
        if selected_chapter == 5:
            return (0, 2, 3)  # Bow, Golden Fleece, Icarus Sandals
        if selected_chapter >= 6:
            return (0, 3, 6)  # chapter-appropriate Bow/Arch, Boots, Hammer/Parrot
    if book == 2:
        return (0, 3, 6)
    if book == 3:
        return (0, 6, 10)     # Arch, Hand of Hercules, Wooden Parrot
    return None


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
    return in_danger and (candidate is None or not candidate.lethal)


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
    """Spend Power-Up only when its native 1.25x boost removes a whole turn."""
    return bool(
        candidate is not None
        and state.attack_potion_available
        and not candidate.lethal
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
    if is_book3_final_gauntlet(state):
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
    if is_boss_encounter(state) and any(candidate.lethal for candidate in ranked):
        return "shortest-lethal"
    return strategy


def should_confirm_book_movie_skip(
    state: DeluxeState | None, probe_count: int,
    chapter_override: int | None = None,
) -> bool:
    """Recognize the uninstrumented movie-skip confirmation between books."""
    return (
        state is not None
        and (
            state.chapter == 10
            or (state.chapter < 1 and chapter_override == 10)
        )
        and is_boss_encounter(state)
        and probe_count >= 20
    )


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


def immediate_defeated_reset_reason(
    state: DeluxeState | None,
    defeated_enemy: str,
    already_reset: set[tuple[int, int, int, str]],
    chapter_override: int | None,
) -> str | None:
    """Return a non-boss route reset only after Lua confirms the defeat."""
    if state is None or state.enemy != defeated_enemy:
        return None
    if is_chapter_boss_defeat(state):
        return None
    return post_victory_reset_reason(state, already_reset, chapter_override)


def should_arm_boss_reset_on_zero_health(
    state: DeluxeState | None,
) -> bool:
    """Chapter bosses arm an exit when Lua confirms their HP reached zero."""
    return state is not None and (
        is_chapter_boss_defeat(state)
        or state.enemy == "Sphinx (Last Riddle)"
    )


def enemy_accepts_candidate(state: DeluxeState, candidate: Candidate) -> bool:
    """Apply known enemy word immunities before strategy ranking."""
    if state.enemy.casefold().startswith("mama roc"):
        return len(candidate.word) > 3
    return True


def is_initial_play_tutorial(
    board: str | None, active_dialog: str | None, state: DeluxeState | None,
    attacks: int,
) -> bool:
    """Recognize Deluxe's fixed PLAY lesson despite a stale launch snapshot."""
    return (
        board == TUTORIAL_PLAY_BOARD
        and active_dialog == "interrupt"
    )


def dialogue_pulse_suppressed(
    boss_reset_pending: bool, treasure_active: bool,
    chapter_transition: bool, menu_transition: bool,
) -> bool:
    """Protect non-dialogue screens from otherwise valid Lua pulses."""
    return (
        boss_reset_pending or treasure_active
        or chapter_transition or menu_transition
    )


def boss_reset_dialog_recovery_allowed(
    source: str, menu_reentry_pending: bool,
    last_boss_reset_key: tuple[int, int, int, str] | None,
) -> bool:
    """Allow only a post-reset result overlay to unblock a missed menu exit."""
    return bool(
        menu_reentry_pending
        and last_boss_reset_key is not None
        and source in {"interrupt", "convpanel"}
    )


def is_unchanged_combat_snapshot(
    current: DeluxeState, submitted: DeluxeState | None
) -> bool:
    """Reject only sequence churn with no combat-relevant state change.

    Enemy HP and board letters can remain unchanged while an enemy attack
    lowers Lex's health or damages tiles. Those snapshots must be processed so
    healing and damage selection use the new state.
    """
    return bool(
        submitted is not None
        and current == replace(submitted, sequence=current.sequence)
    )


def completes_early_ready(state: DeluxeState, early_ready_board: str | None) -> bool:
    """Recognize the completed snapshot belonging to a previously early READY."""
    return early_ready_board is not None and state.board == early_ready_board


def read_seed(log_path: Path) -> tuple[str | None, bool, bool, int | None]:
    """Recover only the latest board/combat state, never replay every old turn."""
    board = None
    ready = False
    done = False
    chapter = None
    if not log_path.exists():
        return board, ready, done, chapter
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = CHAPTER_RE.search(line)
        if match:
            chapter = int(match.group("chapter"))
            # PopCap carries the final board into the next chapter. Keep the
            # latest snapshot when Lua has no reason to emit it again.
            ready = False
            done = False
        for event in BOARD_EVENT_RE.finditer(line):
            board = event.group("board")
            ready = event.group("kind") == "READY"
        if "User clicked ATTACK" in line:
            ready = False
        if DONE_MARKER in line:
            done = True
    return board, ready, done, chapter


def unresolved_play_tutorial(text: str) -> bool:
    """Recognize PLAY when its event predates the runner's tail cursor."""
    plays = list(PLAY_TUTORIAL_RE.finditer(text))
    if not plays:
        return False
    play = plays[-1]
    sequence = int(play.group("sequence"))
    return not any(
        int(match.group("sequence")) == sequence and match.start() > play.start()
        for match in DIALOG_INACTIVE_RE.finditer(text)
    )


def read_latest_dialog(log_path: Path) -> str | None:
    """Recover the most recently reported dialogue or non-combat screen."""
    latest = None
    if not log_path.exists():
        return latest
    text = log_path.read_text(encoding="utf-8", errors="replace")
    events = []
    events.extend((m.start(), m.group("source")) for m in DIALOG_ACTIVE_RE.finditer(text))
    events.extend((m.start(), None) for m in DIALOG_INACTIVE_RE.finditer(text))
    events.extend(
        (m.start(), "treasure" if m.group("kind") == "treasure" else None)
        for m in LEGACY_SCREEN_RE.finditer(text)
    )
    for _, latest in sorted(events):
        pass
    return latest


def read_screen_blocker(log_path: Path) -> str | None:
    """Recover a non-combat screen that must suppress fallback clicks."""
    latest = read_latest_dialog(log_path)
    return latest if latest == "treasure" else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Follow lua.log and play each newly generated board"
    )
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--title", default="Bookworm Adventures")
    parser.add_argument("--layout", choices=("web", "deluxe"), default="web")
    parser.add_argument(
        "--strategy",
        choices=(
            "chapter-aware", "book1-lookahead", "overkill-tier",
            "shortest-lethal", "max-damage",
        ),
        default="chapter-aware",
    )
    parser.add_argument(
        "--telemetry", type=Path,
        help="append Deluxe attack timing samples as JSONL",
    )
    parser.add_argument(
        "--book1-corpus", type=Path,
        help="validated schema-v2 transitions used by book1-lookahead",
    )
    parser.add_argument(
        "--book1-overrides", type=Path,
        help="exact-state JSON decisions for deterministic branch experiments",
    )
    parser.add_argument(
        "--timer-state", type=Path, default=DEFAULT_TIMER_STATE,
        help="persistent chapter timer JSON created by new-run",
    )
    parser.add_argument(
        "--delay", type=float, default=0.08,
        help="frame-safe delay between tile clicks; retries increase this automatically",
    )
    parser.add_argument(
        "--settle", type=float, default=0.15,
        help="short guard before Attack; Deluxe still submits during tile animation",
    )
    parser.add_argument("--poll", type=float, default=0.1)
    parser.add_argument(
        "--input-confirm-timeout", type=float, default=1.5,
        help="seconds to wait for the game's ATTACK acknowledgement before replaying input",
    )
    parser.add_argument(
        "--max-input-attempts", type=int, default=3,
        help="maximum selection attempts for one chosen word",
    )
    parser.add_argument(
        "--auto-dialog", action=argparse.BooleanOptionalAction, default=True,
        help="advance supported Lua-confirmed dialogues (default: enabled)",
    )
    parser.add_argument(
        "--auto-menu-reset", action=argparse.BooleanOptionalAction, default=True,
        help="perform verified boss and route-note menu resets (default: enabled)",
    )
    parser.add_argument(
        "--dialog-stall-delay", type=float, default=2.5,
        help="probe a dialogue after BOARD remains non-ready for this many seconds",
    )
    parser.add_argument(
        "--dialog-probe-interval", type=float, default=0.8,
        help="interval between dialogue clicks while Lua continues withholding READY",
    )
    parser.add_argument(
        "--ready-delay", type=float, default=0.1,
        help="small scheduling delay after Lua confirms tile input is enabled",
    )
    parser.add_argument("--max-attacks", type=int, default=1000)
    parser.add_argument(
        "--max-scrambles", type=int, default=10,
        help="stop after this many no-word Scramble fallbacks",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    log_path = args.log.resolve()
    timer_state = None
    if args.timer_state is not None and args.timer_state.exists():
        timer_state = load_timer_state(args.timer_state)
        print(f"Chapter timing enabled: {args.timer_state}", flush=True)
    board, ready, done, chapter = read_seed(log_path)
    latest_dialog = read_latest_dialog(log_path)
    blocked_screen = latest_dialog if latest_dialog == "treasure" else None
    treasure_selection_started = False
    if ready and blocked_screen == "treasure":
        blocked_screen, treasure_selection_started = (
            clear_stale_treasure_on_ready(blocked_screen, False)
        )
        latest_dialog = None
        print(
            "Startup combat READY superseded stale treasure transition.",
            flush=True,
        )
    active_dialog = (
        latest_dialog if latest_dialog in {"conversation", "levelup"} else None
    )
    deluxe_state = None
    initial_log_text = ""
    initial_log_size = 0
    if args.layout == "deluxe" and log_path.exists():
        with log_path.open("r", encoding="utf-8", errors="replace") as startup_log:
            initial_log_text = startup_log.read()
            initial_log_size = startup_log.tell()
        # Keep the byte boundary represented by the startup snapshot. Startup
        # recovery clicks can synchronously append status-clear telemetry before
        # the follower opens the log. Seeking to the then-current EOF would skip
        # that confirmation and leave the runner in a stale incapacitated state.
        deluxe_state = parse_state(initial_log_text)
    if done:
        label = f"Chapter {chapter}" if chapter is not None else "Current chapter"
        print(f"{label} is already complete.", flush=True)
        return

    controller = X11Keyboard(args.title, args.layout)
    decision_overrides = DecisionOverrides.load(args.book1_overrides)
    submitted_board = None
    submitted_sequence = None
    submitted_at = None
    submitted_attack_at = None
    submitted_candidate: Candidate | None = None
    submitted_state: DeluxeState | None = None
    submitted_strategy: str | None = None
    submitted_frontier: list[Candidate] = []
    submitted_book = None
    submitted_chapter = None
    required_ready_after_overlay = None
    submitted_word: str | None = None
    submitted_path: tuple[int, ...] | None = None
    input_confirmed = True
    input_attempts = 0
    input_confirm_at = float("inf")
    tutorial_play_submitted = False
    tutorial_interrupt_active = False
    reset_encounters: set[tuple[int, int, int, str]] = set()
    movie_skip_confirmed: set[tuple[int, int, int, str]] = set()
    map_enter_encounters: set[tuple[int, int, int, str]] = set()
    rejected_words: set[str] = set()
    dialog_probe_at = (
        time.monotonic() + args.dialog_stall_delay
        if args.layout == "deluxe" and not ready and blocked_screen is None
        else float("inf")
    )
    dialog_probe_count = 0
    chapter_enter_at = float("inf")
    chapter_enter_pending = False
    chapter_enter_attempts = 0
    menu_reentry_at = float("inf")
    menu_reentry_pending = False
    menu_reentry_attempts = 0
    menu_reset_dialog_seen = False
    boss_reset_state: DeluxeState | None = None
    boss_reset_dialog_ready = False
    pending_health_potion_state: DeluxeState | None = None
    pending_health_potion_at = float("inf")
    pending_health_potion_attempts = 0
    player_incapacitated = latest_incapacitation_state(
        initial_log_text, deluxe_state,
    )
    incap_overlay_retry_at = (
        time.monotonic() if player_incapacitated else float("inf")
    )
    incap_purify_pending = False
    incap_purify_attempts = 0
    incap_purify_failed = False
    incap_health_submitted = False
    startup_overlay = latest_unresolved_incapacitation_overlay(initial_log_text)
    if player_incapacitated:
        startup_incap = latest_active_incapacitation_event(initial_log_text)
        startup_recovery = "continue"
        if startup_incap is not None and startup_incap.group("hp") is not None:
            startup_recovery = incapacitation_recovery_action(
                purify_available=startup_incap.group("purify_potion") == "1",
                health_available=startup_incap.group("health_potion") == "1",
                player_hp=float(startup_incap.group("hp")),
                player_max_hp=float(startup_incap.group("max_hp")),
            )
        if startup_recovery == "purify":
            print(
                "Startup incapacitation telemetry confirms Purify is "
                "available; cancelling the lost-turn status.",
                flush=True,
            )
            controller.use_purification_potion(max(0.8, args.delay))
            incap_purify_pending = True
            incap_purify_attempts = 1
            incap_overlay_retry_at = time.monotonic() + 1.0
        elif startup_recovery == "heal_then_continue":
            print(
                "Startup incapacitation telemetry confirms low health and no "
                "Purify; healing before accepting the lost turn.",
                flush=True,
            )
            controller.use_health_potion(max(0.8, args.delay))
            incap_health_submitted = True
            incap_overlay_retry_at = time.monotonic() + 1.0
        else:
            print(
                "Startup snapshot reports an active incapacitation; "
                "resuming native overlay continuation clicks.",
                flush=True,
            )
    elif startup_overlay is not None:
        # The native status predicate clears before the final petrify/freeze
        # card disappears. Recover that last visible continuation separately
        # instead of mistaking the cleared predicate for actionable combat.
        print(
            "Startup log contains an unresolved native "
            f"{startup_overlay.group('kind')} overlay "
            f"(frame {startup_overlay.group('frame')}); clicking its final "
            "continuation area.",
            flush=True,
        )
        controller.dismiss_incapacitation_overlay(args.delay)
    last_boss_reset_key: tuple[int, int, int, str] | None = None
    treasure_selection_started = False
    handled_minigame_prompts: set[int] = set()
    deluxe_words: list[str] = []
    metal_words = frozenset()
    chapter1_hp = {}
    if args.layout == "deluxe":
        root = Path(__file__).resolve().parent
        deluxe_words = list(json.loads(
            (root / "word_dict.json").read_text(encoding="utf-8")
        ))
        metal_words = load_metal_words(
            root.parent / "runtime/deluxe-modded/.tas-data/metals.luc"
        )
        chapter1_hp = load_chapter1_hp_map()
        if args.telemetry is None:
            args.telemetry = root.parent / "runtime/deluxe-modded/tas-timing.jsonl"
        if args.book1_corpus is None:
            args.book1_corpus = args.telemetry
        transition_corpus = TransitionCorpus.load(args.book1_corpus)
    else:
        transition_corpus = TransitionCorpus()
    attacks = 0
    scrambles = 0
    deadline = time.monotonic() + args.timeout
    ready_at = time.monotonic() + args.ready_delay if ready else float("inf")
    early_ready_board: str | None = None

    # Open after seeding and seek to EOF: old boards establish current state but
    # are not replayed as a sequence.
    state_buffer = ""
    with log_path.open("r", encoding="utf-8", errors="replace") as log:
        # Replay anything appended after the startup snapshot, including native
        # confirmation produced by a startup Purify click.
        log.seek(initial_log_size if args.layout == "deluxe" else 0, os.SEEK_SET)
        if args.layout != "deluxe":
            log.seek(0, os.SEEK_END)
        # Close the seed-to-tail race: a non-combat event can arrive after
        # read_seed() but before this cursor is established.
        startup_text = log_path.read_text(encoding="utf-8", errors="replace")
        if lua_runtime_is_waiting(startup_text):
            print("Recovering paused Lua runtime with F5.", flush=True)
            controller.resume_lua_runtime(args.delay)
            deadline = time.monotonic() + args.timeout
        _, refreshed_ready, _, _ = read_seed(log_path)
        refreshed_dialog = read_latest_dialog(log_path)
        if (
            refreshed_dialog == "interrupt"
            and unresolved_play_tutorial(startup_text)
            and not tutorial_play_submitted
        ):
            tutorial_play_submitted = True
            tutorial_interrupt_active = True
            active_dialog = "interrupt"
            print(
                "Recovering fixed fresh-profile PLAY tutorial from active "
                "startup marker.",
                flush=True,
            )
            controller.play_tutorial_play(args.delay)
            deadline = time.monotonic() + args.timeout
        if refreshed_dialog == "treasure" and not refreshed_ready:
            blocked_screen = "treasure"
            active_dialog = None
            refreshed_state = parse_state(
                log_path.read_text(encoding="utf-8", errors="replace")
            ) if args.layout == "deluxe" else None
            treasure_state = refreshed_state or deluxe_state
            slots = None
            if treasure_state is not None:
                slots = treasure_slots_for_state(treasure_state)
            if slots is None:
                contexts = list(TREASURE_CONTEXT_RE.finditer(startup_text))
                if contexts and contexts[-1].group("book") != "nil":
                    slots = treasure_slots_for_context(
                        int(contexts[-1].group("book")),
                        int(contexts[-1].group("selected")),
                    )
            if slots is not None:
                print(
                    f"Recovering startup treasure screen with slots {slots}.",
                    flush=True,
                )
                treasure_selection_started = True
                controller.select_treasures(slots, args.delay)
        map_matches = list(CHAPTER_MAP_RE.finditer(
            startup_text
        ))
        prompt_matches = list(MINIGAME_PROMPT_RE.finditer(startup_text))
        callback_positions = [
            match.start() for match in CHAPTER_ACTION_RE.finditer(startup_text)
            if match.group("action") == "minigame-callback"
        ]
        unresolved_prompt = bool(prompt_matches) and (
            not callback_positions
            or prompt_matches[-1].start() > callback_positions[-1]
        )
        if unresolved_prompt:
            print(
                "Recovering Lua-confirmed mini-game prompt; choosing Yes to skip it.",
                flush=True,
            )
            time.sleep(max(0.8, args.delay))
            controller.confirm_skip_minigame(max(0.8, args.delay))
            handled_minigame_prompts.add(
                int(prompt_matches[-1].group("sequence"))
            )
            deadline = time.monotonic() + args.timeout
        elif map_matches and map_matches[-1].group("enabled") == "true":
            selected = int(map_matches[-1].group("selected"))
            print(
                f"Recovering ready chapter map for Chapter {selected}; entering.",
                flush=True,
            )
            chapter_enter_attempts = 1
            controller.enter_chapter(max(1.0, args.delay))
            deadline = time.monotonic() + args.timeout
        while True:
            token_is_new = (
                deluxe_state is not None
                and deluxe_state.sequence != submitted_sequence
                if args.layout == "deluxe" else board != submitted_board
            )
            if (
                ready and board and token_is_new
                and active_dialog is None and blocked_screen is None
                and time.monotonic() >= ready_at
            ):
                path = None
                if args.layout == "deluxe":
                    if deluxe_state is None or deluxe_state.board != board:
                        recovered = parse_state(
                            log_path.read_text(encoding="utf-8", errors="replace")
                        )
                        if recovered is not None and recovered.board == board:
                            deluxe_state = recovered
                            print(
                                f"Complete state {recovered.sequence} recovered "
                                "for early READY event.",
                                flush=True,
                            )
                        else:
                            early_ready_board = board
                            ready = False
                            print(
                                "READY arrived before its complete Deluxe snapshot; "
                                "waiting for state recovery.",
                                flush=True,
                            )
                            continue
                    if is_unchanged_combat_snapshot(deluxe_state, submitted_state):
                        print(
                            f"Ignoring unchanged READY snapshot "
                            f"{deluxe_state.sequence} for {deluxe_state.enemy}.",
                            flush=True,
                        )
                        submitted_sequence = deluxe_state.sequence
                        ready = False
                        continue
                    ranked = [
                        candidate for candidate in candidates(
                            deluxe_state, deluxe_words, metal_words, args.delay
                        )
                        if (
                            candidate.word not in rejected_words
                            and enemy_accepts_candidate(deluxe_state, candidate)
                        )
                    ]
                    if not ranked:
                        # Sphinx answers are guaranteed to appear in the
                        # rotating board; let Lua publish the next board
                        # instead of spending a scramble on a temporary miss.
                        if SPHINX_ANSWERS.get(deluxe_state.enemy) is not None:
                            print(
                                f"Sphinx answer {SPHINX_ANSWERS[deluxe_state.enemy]} "
                                "not on this board; waiting for Lua board rotation.",
                                flush=True,
                            )
                            submitted_board = board
                            submitted_sequence = deluxe_state.sequence
                            ready = False
                            deadline = time.monotonic() + args.timeout
                            continue
                        if scrambles >= args.max_scrambles:
                            raise RuntimeError(
                                f"Stopped after the safety limit of {args.max_scrambles} scrambles"
                            )
                        scrambles += 1
                        print(
                            f"State {deluxe_state.sequence}: no playable word; "
                            f"Scramble {scrambles}/{args.max_scrambles}.",
                            flush=True,
                        )
                        controller.scramble(args.delay)
                        submitted_board = board
                        submitted_sequence = deluxe_state.sequence
                        ready = False
                        deadline = time.monotonic() + args.timeout
                        continue
                    requested_strategy = args.strategy
                    effective_strategy = strategy_for_state(
                        deluxe_state,
                        "chapter-aware"
                        if requested_strategy == "book1-lookahead"
                        else requested_strategy,
                        chapter,
                    )
                    effective_strategy = boss_finish_strategy(
                        deluxe_state, effective_strategy, ranked
                    )
                    selected, alternatives = choose(ranked, effective_strategy)
                    experimental = decision_overrides.choose(deluxe_state, ranked)
                    if experimental is not None:
                        selected = experimental
                        effective_strategy = "book1-experiment"
                        print(
                            "  experiment: applying exact-state decision "
                            f"{selected.word}/{selected.path}.", flush=True,
                        )
                    elif (
                        requested_strategy == "book1-lookahead"
                        and deluxe_state.book == 1
                        and 1 <= deluxe_state.chapter <= 5
                    ):
                        lookahead = choose_recorded_lookahead(
                            deluxe_state, ranked, transition_corpus
                        )
                        if lookahead is None:
                            print(
                                "  lookahead: fewer than two validated branches; "
                                f"falling back to {effective_strategy}.",
                                flush=True,
                            )
                        else:
                            selected = lookahead
                            effective_strategy = "book1-lookahead"
                            print(
                                "  lookahead: selected from validated recorded "
                                "successors.", flush=True,
                            )
                    riddle_candidate, riddle_answer = sphinx_candidate(
                        deluxe_state.enemy, ranked
                    )
                    if riddle_candidate is not None:
                        selected = riddle_candidate
                        print(
                            f"  Sphinx override: using fixed answer {riddle_answer}.",
                            flush=True,
                        )
                    elif riddle_answer is not None:
                        if sphinx_allows_damage_fallback(
                            deluxe_state.enemy, selected
                        ):
                            print(
                                f"  Sphinx answer {riddle_answer} is absent; "
                                f"using normal combat word {selected.word}.",
                                flush=True,
                            )
                            word, damage, path = (
                                selected.word, selected.damage, selected.path
                            )
                        else:
                            print(
                                f"  Sphinx answer {riddle_answer} is not playable; "
                                "waiting for Lua puzzle-board rotation.",
                                flush=True,
                            )
                            submitted_board = board
                            submitted_sequence = deluxe_state.sequence
                            ready = False
                            deadline = time.monotonic() + args.timeout
                            continue
                    word, damage, path = selected.word, selected.damage, selected.path
                    shortest = alternatives.get("shortest_lethal")
                    maximum = alternatives["max_damage"]
                    print(
                        f"State {deluxe_state.sequence}: {deluxe_state.enemy} "
                        f"HP {deluxe_state.hp:g}/{deluxe_state.max_hp:g}; "
                        f"treasures={','.join(sorted(deluxe_state.treasures)) or 'none'}",
                        flush=True,
                    )
                    warning = validate_chapter1_state(deluxe_state, chapter1_hp)
                    if warning:
                        print(f"  state warning: {warning}", flush=True)
                    print(
                        f"  chose {word} damage={damage:.2f} "
                        f"overkill={selected.overkill:.2f} tier={selected.tier} "
                        f"strategy={effective_strategy} "
                        f"time={selected.predicted_time:.2f}s; "
                        f"shortest={shortest.word if shortest else 'none'}; "
                        f"max={maximum.word}",
                        flush=True,
                    )
                else:
                    word, damage = best_word(board)
                if (
                    args.layout == "deluxe" and deluxe_state is not None
                    and should_use_health_potion(deluxe_state, selected)
                ):
                    print(
                        f"Health potion required at "
                        f"{deluxe_state.player_hp:g}/"
                        f"{deluxe_state.player_max_hp:g}; waiting for native "
                        "consumption confirmation before attacking.",
                        flush=True,
                    )
                    controller.use_health_potion(max(0.8, args.delay))
                    pending_health_potion_state = deluxe_state
                    pending_health_potion_attempts = 1
                    pending_health_potion_at = time.monotonic() + 1.5
                    submitted_board = board
                    submitted_sequence = deluxe_state.sequence
                    ready = False
                    deadline = time.monotonic() + args.timeout
                    continue
                attacks += 1
                print(
                    f"Attack {attacks}: {board} -> {word.upper()} "
                    f"({damage:.2f} estimated damage)",
                    flush=True,
                )
                if (
                    args.layout == "deluxe" and deluxe_state is not None
                    and should_use_powerup_potion(deluxe_state, selected)
                ):
                    print(
                        "Power-Up converts the selected attack into a predicted "
                        "one-shot; activating it.",
                        flush=True,
                    )
                    controller.use_powerup_potion(max(0.8, args.delay))
                if (
                    args.layout == "deluxe" and deluxe_state is not None
                    and should_use_purification_potion(deluxe_state, selected)
                ):
                    # Petrify can end an encounter with Lex still at full
                    # health. Cleanse it before submitting the next word.
                    print(
                        "Purify required before attack: "
                        f"enemy={deluxe_state.enemy}; "
                        f"petrified={int(deluxe_state.player_petrified)}; "
                        "damage_over_time="
                        f"{int(deluxe_state.player_has_damage_over_time)}.",
                        flush=True,
                    )
                    controller.use_purification_potion(max(0.8, args.delay))
                attack_started_at = time.monotonic()
                controller.play_word(
                    board, word, args.delay, args.settle, path,
                    clear_first=False,
                )
                attack_clicked_at = time.monotonic()
                submitted_board = board
                submitted_word = word
                submitted_path = path
                input_confirmed = False
                input_attempts = 1
                input_confirm_at = time.monotonic() + args.input_confirm_timeout
                if deluxe_state is not None:
                    submitted_sequence = deluxe_state.sequence
                    submitted_book, submitted_chapter = telemetry_context(
                        deluxe_state, timer_state,
                    )
                    submitted_at = attack_started_at
                    submitted_attack_at = attack_clicked_at
                    submitted_candidate = selected
                    submitted_state = deluxe_state
                    submitted_strategy = effective_strategy
                    submitted_frontier = list(ranked)
                ready = False
                deadline = time.monotonic() + args.timeout

            # Incapacitation telemetry can arrive continuously while a modal
            # animation loops. Run this retry clock before reading the next
            # line so log traffic cannot starve Purify recovery.
            if (
                player_incapacitated
                and time.monotonic() >= incap_overlay_retry_at
            ):
                if incap_purify_pending:
                    if incap_purify_attempts < 3:
                        incap_purify_attempts += 1
                        print(
                            "Purify is still unconfirmed; retrying the "
                            f"blue potion ({incap_purify_attempts}/3).",
                            flush=True,
                        )
                        controller.use_purification_potion(
                            max(0.8, args.delay)
                        )
                    else:
                        print(
                            "Purify remained unconfirmed after 3 attempts; "
                            "falling back to lost-turn recovery.",
                            flush=True,
                        )
                        incap_purify_pending = False
                        incap_purify_failed = True
                        controller.dismiss_incapacitation_overlay(args.delay)
                else:
                    print(
                        "Native incapacitation overlay is still active; "
                        "retrying its continuation click.",
                        flush=True,
                    )
                    controller.dismiss_incapacitation_overlay(args.delay)
                incap_overlay_retry_at = time.monotonic() + 1.0
                deadline = time.monotonic() + args.timeout

            line = log.readline()
            if not line:
                if (
                    args.auto_dialog
                    and not ready
                    and active_dialog is None
                    and blocked_screen is None
                    and not player_incapacitated
                    and boss_reset_state is None
                    and not menu_reentry_pending
                    and not chapter_enter_pending
                    and time.monotonic() >= dialog_probe_at
                ):
                    dialog_probe_count += 1
                    print(
                        "No READY event after board update; probing the safe "
                        f"dialogue point ({dialog_probe_count}).",
                        flush=True,
                    )
                    controller.advance_dialog("interrupt", args.delay)
                    dialog_probe_at = (
                        time.monotonic() + args.dialog_probe_interval
                    )
                    deadline = time.monotonic() + args.timeout
                if (
                    pending_health_potion_state is not None
                    and time.monotonic() >= pending_health_potion_at
                ):
                    if pending_health_potion_attempts >= 3:
                        raise RuntimeError(
                            "Health potion was not confirmed after 3 safe retries; "
                            "refusing to submit the attack"
                        )
                    pending_health_potion_attempts += 1
                    print(
                        "No native health-potion confirmation; retrying "
                        f"({pending_health_potion_attempts}/3).",
                        flush=True,
                    )
                    controller.use_health_potion(max(0.8, args.delay))
                    pending_health_potion_at = time.monotonic() + 1.5
                    deadline = time.monotonic() + args.timeout
                if menu_reentry_pending and time.monotonic() >= menu_reentry_at:
                    menu_reentry_attempts += 1
                    print(
                        "Retrying Adventure after a blocked menu re-entry "
                        f"({menu_reentry_attempts}).",
                        flush=True,
                    )
                    controller.start_adventure(args.delay)
                    menu_reentry_at = time.monotonic() + 2.0
                    deadline = time.monotonic() + args.timeout
                if chapter_enter_pending and time.monotonic() >= chapter_enter_at:
                    chapter_enter_attempts += 1
                    print(
                        "Entering the next chapter from the chapter map "
                        f"(attempt {chapter_enter_attempts}/20).",
                        flush=True,
                    )
                    # Map animations can still own the Enter hotspot when the
                    # epilogue's final Lua event arrives. Retry conservatively;
                    # every fresh board/dialog/chapter event below disarms it.
                    chapter_enter_pending = chapter_enter_attempts < 20
                    chapter_enter_at = (
                        time.monotonic() + 3.0
                        if chapter_enter_pending else float("inf")
                    )
                    controller.enter_chapter(max(1.0, args.delay))
                    dialog_probe_at = time.monotonic() + args.dialog_stall_delay
                    deadline = time.monotonic() + args.timeout
                if (
                    not tutorial_play_submitted
                    and is_initial_play_tutorial(
                        board, active_dialog, deluxe_state, attacks
                    )
                ):
                    tutorial_play_submitted = True
                    print("Completing fixed fresh-profile PLAY tutorial.", flush=True)
                    controller.play_tutorial_play(args.delay)
                    # The Lua dialogue marker remains ``levelup`` while the
                    # lesson hands control back to combat.  Do not let the
                    # generic recovery probe click tiles out from under the
                    # fixed tutorial sequence during that handoff.
                    dialog_probe_at = float("inf")
                    deadline = time.monotonic() + args.timeout
                    time.sleep(args.poll)
                    continue
                if (
                    not input_confirmed
                    and not player_incapacitated
                    and active_dialog is None
                    and blocked_screen is None
                    and time.monotonic() >= input_confirm_at
                ):
                    if input_attempts >= args.max_input_attempts:
                        assert submitted_word is not None
                        rejected_words.add(submitted_word)
                        print(
                            f"Blacklisting unacknowledged word "
                            f"{submitted_word.upper()} after {input_attempts} attempts; "
                            "trying the next candidate.",
                            flush=True,
                        )
                        controller.dismiss_invalid_word_dialog(args.delay)
                        submitted_sequence = None
                        submitted_state = None
                        submitted_candidate = None
                        submitted_word = None
                        submitted_path = None
                        input_confirmed = True
                        input_confirm_at = float("inf")
                        ready = True
                        ready_at = time.monotonic() + args.ready_delay
                        continue
                    assert submitted_word is not None and submitted_board is not None
                    input_attempts += 1
                    if timer_state is not None:
                        mark_current_issue(
                            timer_state,
                            f"input-retry:{submitted_word.upper()}",
                        )
                        save_timer_state(args.timer_state, timer_state)
                        save_run_history(timer_state)
                    print(
                        f"No ATTACK acknowledgement; clearing and retrying "
                        f"{submitted_word.upper()} ({input_attempts}/{args.max_input_attempts}).",
                        flush=True,
                    )
                    controller.dismiss_invalid_word_dialog(args.delay)
                    retry_delay = args.delay * input_attempts
                    controller.play_word(
                        submitted_board, submitted_word, retry_delay, args.settle,
                        submitted_path,
                    )
                    input_confirm_at = time.monotonic() + args.input_confirm_timeout
                if args.layout == "deluxe":
                    polled_state = parse_state(
                        log_path.read_text(encoding="utf-8", errors="replace")
                    )
                    if (
                        polled_state is not None
                        and (
                            deluxe_state is None
                            or polled_state.sequence > deluxe_state.sequence
                        )
                    ):
                        deluxe_state = polled_state
                        board = polled_state.board
                        ready = True
                        ready_at = time.monotonic() + args.ready_delay
                        print(
                            f"Complete state {polled_state.sequence} recovered from log.",
                            flush=True,
                        )
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for the next combat log event")
                time.sleep(args.poll)
                continue

            line = line.rstrip("\r\n")
            dialog_active = DIALOG_ACTIVE_RE.search(line)
            if dialog_active:
                active_dialog = dialog_active.group("source")
                pending_health_potion_state = None
                pending_health_potion_at = float("inf")
                pending_health_potion_attempts = 0
                old_blocked_screen = blocked_screen
                old_treasure_selection = treasure_selection_started
                blocked_screen, treasure_selection_started = (
                    clear_stale_treasure_transition(
                        active_dialog, blocked_screen, treasure_selection_started
                    )
                )
                if (
                    old_blocked_screen == "treasure" or old_treasure_selection
                ) and blocked_screen is None and not treasure_selection_started:
                    print(
                        "Native conversation superseded stale treasure "
                        "transition; dialogue pulses rearmed.",
                        flush=True,
                    )
                ready = False
                input_confirm_at = float("inf")
                if deluxe_state is not None:
                    required_ready_after_overlay = max(
                        required_ready_after_overlay or -1,
                        deluxe_state.sequence,
                    )
                if not input_confirmed:
                    print(
                        "Dialogue interrupted pending tile input; discarding "
                        "it until a newer READY sequence.", flush=True,
                    )
                    submitted_board = None
                    submitted_word = None
                    submitted_path = None
                    submitted_sequence = None
                    submitted_state = None
                    submitted_candidate = None
                    submitted_at = None
                    submitted_attack_at = None
                    input_confirmed = True
                    input_attempts = 0
                if (
                    not tutorial_play_submitted
                    and is_initial_play_tutorial(
                        board, active_dialog, deluxe_state, attacks
                    )
                ):
                    tutorial_play_submitted = True
                    print("Completing fixed fresh-profile PLAY tutorial.", flush=True)
                    controller.play_tutorial_play(args.delay)
                    deadline = time.monotonic() + args.timeout
            play_tutorial = PLAY_TUTORIAL_RE.search(line)
            if play_tutorial and not tutorial_play_submitted:
                tutorial_play_submitted = True
                tutorial_interrupt_active = True
                active_dialog = "interrupt"
                print("Completing fixed fresh-profile PLAY tutorial.", flush=True)
                controller.play_tutorial_play(args.delay)
                deadline = time.monotonic() + args.timeout
            dialog_inactive = DIALOG_INACTIVE_RE.search(line)
            if dialog_inactive:
                active_dialog = None
                tutorial_interrupt_active = False
                if menu_reset_dialog_seen and menu_reentry_pending:
                    print(
                        "Post-boss result overlay closed after blocking the "
                        "menu exit; retrying the full battle-menu reset.",
                        flush=True,
                    )
                    reset_from_battle(controller, MenuTiming())
                    menu_reset_dialog_seen = False
                    menu_reentry_attempts = 0
                    menu_reentry_at = time.monotonic() + 2.0
                    deadline = time.monotonic() + args.timeout
                if required_ready_after_overlay is not None:
                    print(
                        "Dialogue exited; waiting for a newer native READY "
                        "sequence before touching the rack.", flush=True,
                    )
            dialog_pulse = DIALOG_PULSE_RE.search(line)
            if dialog_pulse and args.auto_dialog:
                source = dialog_pulse.group("source")
                pulse = int(dialog_pulse.group("pulse"))
                recover_blocked_reset = boss_reset_dialog_recovery_allowed(
                    source, menu_reentry_pending, last_boss_reset_key
                )
                suppress = dialogue_pulse_suppressed(
                    boss_reset_state is not None,
                    blocked_screen == "treasure" or treasure_selection_started,
                    chapter_enter_pending or chapter_enter_at != float("inf"),
                    (menu_reentry_pending or menu_reentry_at != float("inf"))
                    and not recover_blocked_reset,
                )
                # PLAY is submitted through its fixed rack, never by clicking
                # the generic interrupt target over the lesson.
                if source == "interrupt" and (
                    board == TUTORIAL_PLAY_BOARD or tutorial_interrupt_active
                ):
                    suppress = True
                if suppress:
                    print(
                        f"Lua dialogue pulse {pulse}: source={source}; "
                        "suppressed during special-screen transition.", flush=True,
                    )
                else:
                    if recover_blocked_reset:
                        menu_reset_dialog_seen = True
                    destination = (
                        "Continue" if source == "levelup" else "safe arena point"
                    )
                    print(
                        f"Lua dialogue pulse {pulse}: source={source}; "
                        f"clicking {destination}.", flush=True,
                    )
                    controller.advance_dialog(source, args.delay)
            stunned_event = PLAYER_STUNNED_RE.search(line)
            if stunned_event and stunned_event.group("active") == "1":
                incapacitation = stunned_event.group("kind").casefold()
                player_incapacitated = True
                input_confirm_at = float("inf")
                ready = False
                if deluxe_state is not None:
                    required_ready_after_overlay = max(
                        required_ready_after_overlay or -1,
                        deluxe_state.sequence,
                    )
                if not input_confirmed:
                    print(
                        "Incapacitation interrupted pending tile input; "
                        "discarding it until a newer READY sequence.", flush=True,
                    )
                    submitted_board = None
                    submitted_word = None
                    submitted_path = None
                    submitted_sequence = None
                    submitted_state = None
                    submitted_candidate = None
                    submitted_at = None
                    submitted_attack_at = None
                    input_confirmed = True
                    input_attempts = 0
                purify_available = (
                    stunned_event.group("purify_potion") == "1"
                    if stunned_event.group("purify_potion") is not None
                    else False
                )
                live_hp = (
                    float(stunned_event.group("hp"))
                    if stunned_event.group("hp") is not None else -1
                )
                live_max_hp = (
                    float(stunned_event.group("max_hp"))
                    if stunned_event.group("max_hp") is not None else -1
                )
                health_available = (
                    stunned_event.group("health_potion") == "1"
                    if stunned_event.group("health_potion") is not None
                    else False
                )
                recovery = incapacitation_recovery_action(
                    purify_available=purify_available,
                    health_available=health_available,
                    player_hp=live_hp,
                    player_max_hp=live_max_hp,
                )
                if (
                    recovery == "purify" and not incap_purify_pending
                    and not incap_purify_failed
                ):
                    print(
                        f"Lua confirmed Lex is {incapacitation} and Purify is "
                        "available; cancelling the lost-turn status.",
                        flush=True,
                    )
                    controller.use_purification_potion(max(0.8, args.delay))
                    incap_purify_pending = True
                    incap_purify_attempts = 1
                    incap_overlay_retry_at = time.monotonic() + 1.0
                elif recovery == "heal_then_continue" and not incap_health_submitted:
                    print(
                        f"Purify unavailable and Lex is at {live_hp:g}/"
                        f"{live_max_hp:g}; using a confirmed health potion "
                        "before accepting the lost turn.",
                        flush=True,
                    )
                    controller.use_health_potion(max(0.8, args.delay))
                    incap_health_submitted = True
                elif not incap_purify_pending:
                    print(
                        f"Lua confirmed Lex is {incapacitation}; Purify is "
                        "unavailable, waiting for the native grid overlay.",
                        flush=True,
                    )
            elif (
                stunned_event and stunned_event.group("active") == "0"
            ):
                player_incapacitated = False
                incap_purify_pending = False
                incap_purify_attempts = 0
                incap_purify_failed = False
                incap_health_submitted = False
                incap_overlay_retry_at = float("inf")
                print(
                    "Lua confirmed incapacitation ended; clicking the final "
                    "native continuation card once UI ownership has returned.",
                    flush=True,
                )
                controller.dismiss_incapacitation_overlay(args.delay)
                deadline = time.monotonic() + args.timeout
                print(
                    "Incapacitation cleared; waiting for a newer native READY "
                    "sequence before touching the rack.", flush=True,
                )
            incap_overlay_event = INCAP_OVERLAY_RE.search(line)
            if incap_overlay_event:
                if incap_purify_pending:
                    frame = incap_overlay_event.group("frame")
                    if frame.endswith("done") and incap_purify_attempts < 3:
                        incap_purify_attempts += 1
                        print(
                            f"Native {frame} frame is stable and Purify is "
                            f"unconfirmed; retrying the blue potion "
                            f"({incap_purify_attempts}/3).",
                            flush=True,
                        )
                        controller.use_purification_potion(
                            max(0.8, args.delay)
                        )
                        incap_overlay_retry_at = time.monotonic() + 1.0
                    else:
                        print(
                            "Native incapacitation overlay remains active while "
                            "Purify confirmation is pending; continuation click "
                            "suppressed.",
                            flush=True,
                        )
                else:
                    overlay_hp = (
                        float(incap_overlay_event.group("hp"))
                        if incap_overlay_event.group("hp") is not None else -1
                    )
                    overlay_max_hp = (
                        float(incap_overlay_event.group("max_hp"))
                        if incap_overlay_event.group("max_hp") is not None else -1
                    )
                    must_heal = (
                        incap_purify_failed
                        and incap_overlay_event.group("health_potion") == "1"
                        and 0 < overlay_hp <= min(4.0, overlay_max_hp)
                        and not incap_health_submitted
                    )
                    if must_heal:
                        print(
                            f"Purify failed and Lex fell to {overlay_hp:g}/"
                            f"{overlay_max_hp:g}; healing before accepting "
                            "the next lost turn.",
                            flush=True,
                        )
                        controller.use_health_potion(max(0.8, args.delay))
                        incap_health_submitted = True
                    print(
                        "Lua confirmed the native "
                        f"{incap_overlay_event.group('kind')} overlay is active "
                        f"(frame {incap_overlay_event.group('frame')}); "
                        "clicking its continuation area.",
                        flush=True,
                    )
                    controller.dismiss_incapacitation_overlay(args.delay)
                # The frame edge can arrive while the card is still animating,
                # before MouseUp accepts the click. Keep pulsing until Lua
                # reports that the native incapacitation predicate cleared.
                incap_overlay_retry_at = time.monotonic() + 1.0
            if timer_state is not None and process_timer_line(
                timer_state, line, time.time()
            ):
                save_timer_state(args.timer_state, timer_state)
                save_run_history(timer_state)
                update_tas_best(timer_state)
                timed = timer_state["current"]
                print(
                    f"Timer entered Book {timed['book']} Chapter "
                    f"{timed['chapter']}.",
                    flush=True,
                )
            elif timer_state is not None and "AUTOMATION_READY_SEQ=" in line:
                save_timer_state(args.timer_state, timer_state)
                save_run_history(timer_state)
            map_event = CHAPTER_MAP_RE.search(line)
            if map_event:
                selected = int(map_event.group("selected"))
                if map_event.group("enabled") == "true":
                    chapter = selected if selected >= 1 else chapter
                    chapter_enter_attempts += 1
                    print(
                        f"Chapter map ready for Chapter {selected}; entering "
                        f"(event {chapter_enter_attempts}).",
                        flush=True,
                    )
                    controller.enter_chapter(max(1.0, args.delay))
                    dialog_probe_at = float("inf")
                    deadline = time.monotonic() + args.timeout
                else:
                    print(
                        f"Chapter {selected} Enter accepted; waiting for its next screen.",
                        flush=True,
                    )
                    chapter_enter_pending = False
                    chapter_enter_at = float("inf")
            action_event = CHAPTER_ACTION_RE.search(line)
            if action_event:
                print(
                    f"Chapter-map action confirmed: {action_event.group('action')}.",
                    flush=True,
                )
                deadline = time.monotonic() + args.timeout
            if LUA_WAIT_MARKER in line:
                print("Lua runtime entered its explicit wait; resuming with F5.", flush=True)
                controller.resume_lua_runtime(args.delay)
                deadline = time.monotonic() + args.timeout
            treasure_context = TREASURE_CONTEXT_RE.search(line)
            if (
                treasure_context and blocked_screen == "treasure"
                and args.auto_dialog and not treasure_selection_started
                and treasure_context.group("book") != "nil"
            ):
                slots = treasure_slots_for_context(
                    int(treasure_context.group("book")),
                    int(treasure_context.group("selected")),
                )
                if slots is not None:
                    print(
                        f"Selecting route treasure slots {slots} from live "
                        "chapter context.",
                        flush=True,
                    )
                    treasure_selection_started = True
                    controller.select_treasures(slots, args.delay)
            minigame_prompt = MINIGAME_PROMPT_RE.search(line)
            if (
                minigame_prompt
                and int(minigame_prompt.group("sequence"))
                not in handled_minigame_prompts
            ):
                print(
                    "Lua-confirmed mini-game prompt; choosing Yes to skip it.",
                    flush=True,
                )
                # The hook runs as the prompt is being constructed. Give its
                # buttons one frame-safe pause before clicking No.
                time.sleep(max(0.8, args.delay))
                controller.confirm_skip_minigame(max(0.8, args.delay))
                handled_minigame_prompts.add(
                    int(minigame_prompt.group("sequence"))
                )
                deadline = time.monotonic() + args.timeout
            dialog = LEGACY_SCREEN_RE.search(line)
            if dialog and dialog.group("kind") == "none":
                was_blocked = blocked_screen is not None
                blocked_screen = None
                treasure_selection_started = False
                active_dialog = None
                if not input_confirmed:
                    # A dialogue can appear after selection but before Attack
                    # becomes clickable. Its blocked time is not a failed input
                    # attempt; restart the full retry budget after it exits.
                    input_attempts = 1
                    input_confirm_at = (
                        time.monotonic() + args.input_confirm_timeout
                    )
                    print(
                        "Input retry rearmed after dialogue exit.",
                        flush=True,
                    )
                if was_blocked and not ready:
                    dialog_probe_at = time.monotonic() + args.dialog_stall_delay
                    dialog_probe_count = 0
                    print(
                        "Treasure screen exited; dialogue fallback rearmed.",
                        flush=True,
                    )
                if boss_reset_state is not None and boss_reset_dialog_ready:
                    last_boss_reset_key = encounter_key(boss_reset_state)
                    reset_encounters.add(last_boss_reset_key)
                    print(
                        f"Lua confirmed the post-defeat overlay for "
                        f"{boss_reset_state.enemy} closed; resetting through "
                        "the main menu.",
                        flush=True,
                    )
                    reset_from_battle(controller, MenuTiming())
                    boss_reset_state = None
                    boss_reset_dialog_ready = False
                    menu_reentry_pending = True
                    menu_reentry_attempts = 0
                    menu_reentry_at = time.monotonic() + 2.0
                    submitted_sequence = (
                        deluxe_state.sequence if deluxe_state is not None else None
                    )
                    input_confirmed = True
                    input_confirm_at = float("inf")
                    ready = False
                    dialog_probe_at = float("inf")
                    deadline = time.monotonic() + args.timeout
            elif dialog and dialog.group("kind") == "treasure":
                blocked_screen = "treasure"
                active_dialog = None
                # A treasure screen is definitive proof that the Adventure
                # re-entry succeeded; do not keep spraying title-screen clicks.
                menu_reentry_pending = False
                menu_reentry_at = float("inf")
                # Treasure Continue transitions directly into the next chapter.
                # A boss-epilogue map click must never race treasure selection.
                chapter_enter_pending = False
                chapter_enter_at = float("inf")
                ready = False
                # Reaching treasure selection proves the preceding combat is
                # over even if Wine mangled its ATTACK acknowledgement. Never
                # replay that combat word on this non-combat screen or later.
                input_confirmed = True
                input_confirm_at = float("inf")
                dialog_probe_at = float("inf")
                print(
                    "Treasure screen detected; automatic dialogue clicks paused.",
                    flush=True,
                )
                if args.auto_dialog and (
                    submitted_state is not None or deluxe_state is not None
                ):
                    treasure_state = submitted_state or deluxe_state
                    assert treasure_state is not None
                    slots = treasure_slots_for_state(treasure_state)
                    if slots is not None:
                        print(
                            f"Selecting route treasure slots {slots} after "
                            f"{treasure_state.enemy}.",
                            flush=True,
                        )
                        treasure_selection_started = True
                        controller.select_treasures(slots, args.delay)
            attack_submitted_event = ATTACK_SUBMITTED_RE.search(line)
            if attack_submitted_event or "User clicked ATTACK" in line:
                input_confirmed = True
                input_confirm_at = float("inf")
                if input_attempts > 1:
                    print(
                        f"ATTACK acknowledged after {input_attempts} input attempts.",
                        flush=True,
                    )
                if attacks >= args.max_attacks:
                    raise RuntimeError(
                        f"Stopped after the safety limit of {args.max_attacks} attacks"
                    )
            zero_health_event = ZERO_HEALTH_RE.search(line)
            if zero_health_event and tutorial_play_submitted:
                # The scripted PLAY tutorial disables conversation probes while
                # it owns the rack.  Its first post-victory Cassandra overlay
                # is not consistently reported by convpanel.Active(), so the
                # zero-health edge is the reliable point at which generic
                # dialogue recovery can safely resume.
                active_dialog = None
                dialog_probe_at = time.monotonic() + args.dialog_probe_interval
            if (
                zero_health_event and args.auto_menu_reset
                and submitted_state is not None
                # Chapter bosses arm on zero health, then exit at the native
                # reset-ready/save edge to skip their long post-victory
                # sequence. Route checkpoints use DEFEATED instead.
                and should_arm_boss_reset_on_zero_health(submitted_state)
                and encounter_key(submitted_state) not in reset_encounters
                and boss_reset_state is None
            ):
                print(
                    f"Lua confirmed {zero_health_event.group('enemy')} reached zero HP; "
                    "waiting for the Lua-confirmed save-ready edge.",
                    flush=True,
                )
                boss_reset_state = submitted_state
                dialog_probe_at = float("inf")
                input_confirmed = True
                input_confirm_at = float("inf")
                ready = False
                deadline = time.monotonic() + args.timeout
            reset_ready_event = RESET_READY_RE.search(line)
            if reset_ready_event and boss_reset_state is not None:
                last_boss_reset_key = encounter_key(boss_reset_state)
                reset_encounters.add(last_boss_reset_key)
                print(
                    f"Lua confirmed {reset_ready_event.group('enemy')} death animation "
                    "settled before the result interrupt; immediate reset "
                    "through the main menu.",
                    flush=True,
                )
                reset_from_battle(controller, MenuTiming())
                boss_reset_state = None
                boss_reset_dialog_ready = False
                menu_reentry_pending = True
                menu_reentry_attempts = 0
                menu_reentry_at = time.monotonic() + 2.0
                submitted_sequence = (
                    deluxe_state.sequence if deluxe_state is not None else None
                )
                input_confirmed = True
                input_confirm_at = float("inf")
                ready = False
                deadline = time.monotonic() + args.timeout
            defeated_event = DEFEATED_RE.search(line)
            if defeated_event:
                pending_health_potion_state = None
                pending_health_potion_at = float("inf")
                pending_health_potion_attempts = 0
            if (
                defeated_event and args.auto_menu_reset
                and boss_reset_state is None
            ):
                reset_reason = immediate_defeated_reset_reason(
                    submitted_state, defeated_event.group("enemy"),
                    reset_encounters, chapter,
                )
                if reset_reason is not None:
                    assert submitted_state is not None
                    reset_encounters.add(encounter_key(submitted_state))
                    print(
                        f"Lua confirmed {defeated_event.group('enemy')} defeated; "
                        f"menu reset {reset_reason}.",
                        flush=True,
                    )
                    reset_from_battle(controller, MenuTiming())
                    # An ambient Lex line on the main menu can consume the
                    # Adventure click. Retry it until combat telemetry proves
                    # that re-entry completed.
                    menu_reentry_pending = True
                    menu_reentry_attempts = 0
                    menu_reentry_at = time.monotonic() + 2.0
                    submitted_sequence = (
                        deluxe_state.sequence if deluxe_state is not None else None
                    )
                    input_confirmed = True
                    input_confirm_at = float("inf")
                    ready = False
                    deadline = time.monotonic() + args.timeout
            if args.layout == "deluxe":
                state_buffer = (state_buffer + "\n" + line)[-32768:]
            new_state = parse_state(state_buffer) if args.layout == "deluxe" else None
            if new_state is not None and (
                deluxe_state is None or new_state.sequence >= deluxe_state.sequence
            ):
                if pending_health_potion_state is not None and health_potion_confirmed(
                    pending_health_potion_state, new_state
                ):
                    print(
                        "Native health-potion consumption confirmed: "
                        f"HP {pending_health_potion_state.player_hp:g} -> "
                        f"{new_state.player_hp:g}; potion_available="
                        f"{int(new_state.health_potion_available)}.",
                        flush=True,
                    )
                    pending_health_potion_state = None
                    pending_health_potion_at = float("inf")
                    pending_health_potion_attempts = 0
                new_key = encounter_key(new_state)
                if (
                    last_boss_reset_key == new_key
                    and new_state.hp >= new_state.max_hp > 0
                ):
                    # Re-entering the same full-health boss means the exit beat
                    # the save commit. Allow one replay instead of deadlocking
                    # behind the at-most-once reset and unchanged-state guards.
                    print(
                        f"Boss reset replayed {new_state.enemy}; clearing reset guard.",
                        flush=True,
                    )
                    reset_encounters.discard(new_key)
                    last_boss_reset_key = None
                    submitted_state = None
                    submitted_sequence = None
                deluxe_state = new_state
                board = new_state.board
                if completes_early_ready(new_state, early_ready_board):
                    ready = True
                    ready_at = time.monotonic() + args.ready_delay
                    early_ready_board = None
                    print(
                        f"Complete state {new_state.sequence} recovered for "
                        "early READY event.",
                        flush=True,
                    )
            match = CHAPTER_RE.search(line)
            if match:
                if chapter_enter_attempts and submitted_state is not None:
                    map_enter_encounters.add(encounter_key(submitted_state))
                chapter = int(match.group("chapter"))
                menu_reentry_pending = False
                menu_reentry_at = float("inf")
                chapter_enter_pending = False
                chapter_enter_at = float("inf")
                submitted_board = None
                ready = False
                print(f"Entered Chapter {chapter}.", flush=True)
            for event in BOARD_EVENT_RE.finditer(line):
                if chapter_enter_attempts and submitted_state is not None:
                    map_enter_encounters.add(encounter_key(submitted_state))
                board = event.group("board")
                if (
                    not tutorial_play_submitted
                    and is_initial_play_tutorial(
                        board, active_dialog, deluxe_state, attacks
                    )
                ):
                    tutorial_play_submitted = True
                    print("Completing fixed fresh-profile PLAY tutorial.", flush=True)
                    controller.play_tutorial_play(args.delay)
                    deadline = time.monotonic() + args.timeout
                menu_reentry_pending = False
                menu_reentry_at = float("inf")
                chapter_enter_pending = False
                chapter_enter_at = float("inf")
                # A transition also proves that Attack was accepted if Wine
                # happened to mangle the acknowledgement line in the console.
                if event.group("kind") == "BOARD" and not input_confirmed:
                    input_confirmed = True
                    input_confirm_at = float("inf")
                    if attacks >= args.max_attacks:
                        raise RuntimeError(
                            f"Stopped after the safety limit of {args.max_attacks} attacks"
                        )
                if event.group("kind") == "READY":
                    if blocked_screen == "treasure" or treasure_selection_started:
                        blocked_screen, treasure_selection_started = (
                            clear_stale_treasure_on_ready(
                                blocked_screen, treasure_selection_started
                            )
                        )
                        print(
                            "Native combat READY superseded stale treasure "
                            "transition; input and dialogue pulses rearmed.",
                            flush=True,
                        )
                    ready_sequence = (
                        deluxe_state.sequence if deluxe_state is not None else -1
                    )
                    if not ready_sequence_is_fresh(
                        ready_sequence, required_ready_after_overlay,
                    ):
                        ready = False
                        print(
                            f"Ignoring stale READY sequence {ready_sequence}; "
                            "an overlay owned the previous rack state.", flush=True,
                        )
                        continue
                    if required_ready_after_overlay is not None:
                        print(
                            f"Fresh READY sequence {ready_sequence} confirmed "
                            "after overlay exit; rack input rearmed.", flush=True,
                        )
                        required_ready_after_overlay = None
                    dialog_probe_at = float("inf")
                    dialog_probe_count = 0
                    if (
                        args.layout == "deluxe" and submitted_at is not None
                        and submitted_candidate is not None and submitted_state is not None
                        and deluxe_state is not None
                    ):
                        sample = {
                            "schema_version": TELEMETRY_SCHEMA_VERSION,
                            "run_id": (
                                timer_state.get("started_at_iso")
                                if timer_state is not None else None
                            ),
                            "book": submitted_book,
                            "chapter": submitted_chapter,
                            "stage": submitted_state.stage,
                            "clean": input_attempts == 1,
                            "issues": (
                                [] if input_attempts == 1
                                else [f"input-attempts:{input_attempts}"]
                            ),
                            "strategy": submitted_strategy,
                            "state_fingerprint": state_fingerprint(submitted_state),
                            "before": state_payload(submitted_state),
                            "action": candidate_payload(submitted_candidate),
                            "frontier": [
                                candidate_payload(candidate)
                                for candidate in pareto_candidates(
                                    submitted_frontier
                                )
                            ],
                            "after": state_payload(deluxe_state),
                            "timing": {
                                "ready_seconds": time.monotonic() - submitted_at,
                                "input_seconds": (
                                    submitted_attack_at - submitted_at
                                    if submitted_attack_at is not None else None
                                ),
                                "resolution_seconds": (
                                    time.monotonic() - submitted_attack_at
                                    if submitted_attack_at is not None else None
                                ),
                                "input_attempts": input_attempts,
                            },
                            # Flat v1-compatible fields remain during migration.
                            "sequence": submitted_state.sequence,
                            "enemy": submitted_state.enemy,
                            "hp": submitted_state.hp,
                            "word": submitted_candidate.word,
                            "letters": len(submitted_candidate.word),
                            "damage": submitted_candidate.damage,
                            "overkill": submitted_candidate.overkill,
                            "tier": submitted_candidate.tier,
                            "gems_used": submitted_candidate.gem_count,
                            "predicted_seconds": submitted_candidate.predicted_time,
                            "actual_seconds": time.monotonic() - submitted_at,
                            "next_sequence": deluxe_state.sequence,
                            "next_enemy": deluxe_state.enemy,
                            "next_hp": deluxe_state.hp,
                            "enemy_defeated": deluxe_state.enemy != submitted_state.enemy,
                            "observed_damage": (
                                submitted_state.hp - deluxe_state.hp
                                if deluxe_state.enemy == submitted_state.enemy else None
                            ),
                        }
                        assert args.telemetry is not None
                        args.telemetry.parent.mkdir(parents=True, exist_ok=True)
                        with args.telemetry.open("a", encoding="utf-8") as output:
                            output.write(json.dumps(sample, sort_keys=True) + "\n")
                        submitted_at = None
                        submitted_attack_at = None
                        submitted_strategy = None
                        submitted_frontier = []
                    ready = True
                    ready_at = time.monotonic() + args.ready_delay
                    print(f"Board ready: {board}", flush=True)
                else:
                    dialog_probe_at = time.monotonic() + args.dialog_stall_delay
                    dialog_probe_count = 0
                    print(f"Board update: {board}", flush=True)
            if DONE_MARKER in line:
                label = f"Chapter {chapter}" if chapter is not None else "Chapter"
                print(f"{label} complete after {attacks} automated attacks.", flush=True)
                return


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, RuntimeError, TimeoutError) as error:
        print(f"continuous runner stopped: {error}", file=sys.stderr)
        raise SystemExit(1)
