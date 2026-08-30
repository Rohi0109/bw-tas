"""Continuously solve boards emitted by the Lua automation hook."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from live_runner import X11Keyboard, best_word
from deluxe_optimizer import (
    Candidate, DeluxeState, candidates, choose, load_chapter1_hp_map,
    load_metal_words, parse_state, strategy_for_state, validate_chapter1_state,
)
from deluxe_route import (
    encounter_key, is_boss_encounter, is_chapter_boss_defeat,
    post_victory_reset_reason,
)
from menu_runner import MenuTiming, reset_from_battle
from run_timer import (
    DEFAULT_STATE as DEFAULT_TIMER_STATE,
    load_state as load_timer_state,
    process_line as process_timer_line,
    save_state as save_timer_state,
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
DIALOG_RE = re.compile(
    r"AUTOMATION_DIALOG=(?P<kind>[a-z]+)\|(?P<sequence>\d+)\|E"
)
DEFEATED_RE = re.compile(r"AUTOMATION_DEFEATED=(?P<enemy>[^|]+)\|E")
ZERO_HEALTH_RE = re.compile(r"AUTOMATION_ZERO_HEALTH=(?P<enemy>[^|]+)\|E")
RESET_READY_RE = re.compile(
    r"AUTOMATION_BOSS_RESET_READY=(?P<enemy>[^|]+)\|E"
)
PLAYER_STUNNED_RE = re.compile(
    r"AUTOMATION_PLAYER_STUNNED=(?P<active>[01])"
    r"(?:\|(?P<hp>-?\d+(?:\.\d+)?)\|(?P<max_hp>-?\d+(?:\.\d+)?)"
    r"\|(?P<health_potion>[01]))?\|E"
)
CHAPTER_MAP_RE = re.compile(
    r"AUTOMATION_CHAPTER_MAP=(?P<book>nil|\d+)\|"
    r"(?P<current>nil|\d+)\|(?P<chapter>nil|\d+)\|"
    r"(?P<selected>-?\d+)\|(?P<enabled>true|false)\|E"
)
CHAPTER_ACTION_RE = re.compile(
    r"AUTOMATION_CHAPTER_ACTION=(?P<action>[a-z-]+)\|E"
)
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
    """Heal before a nonlethal turn when Lex has at most four hearts.

    Hydra and the Book 3 final gauntlet retain their conservative full-heal
    rules because leaving either sequence discards substantially more progress.
    """
    if state.player_hp < 0 or state.player_max_hp <= 0:
        return False
    if not state.health_potion_available:
        return False
    in_danger = (
        state.player_hp <= min(4.0, state.player_max_hp)
        and state.player_hp < state.player_max_hp
    )
    if state.player_stunned and in_danger:
        return True
    if state.enemy.startswith("Hydra (") or is_book3_final_gauntlet(state):
        return state.player_hp < state.player_max_hp
    return (
        candidate is not None
        and not candidate.lethal
        and in_danger
    )


def should_heal_during_stun(state: DeluxeState | None) -> bool:
    """Heal when a live stun has invalidated the already-submitted attack."""
    return bool(
        state is not None
        and state.health_potion_available
        and 0 < state.player_hp <= min(4.0, state.player_max_hp)
        and state.player_hp < state.player_max_hp
    )


def should_use_purification_potion(state: DeluxeState) -> bool:
    """Cleanse known petrify enemies and the Book 3 final gauntlet."""
    if is_book3_final_gauntlet(state):
        return True
    return (
        state.enemy in PURIFY_AFTER_HIT_ENEMIES
        and state.hp < state.max_hp
    )


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
        and active_dialog == "levelup"
    )


def is_unchanged_combat_snapshot(
    current: DeluxeState, submitted: DeluxeState | None
) -> bool:
    """Reject READY churn before the submitted attack changes the enemy."""
    return (
        submitted is not None
        and current.enemy == submitted.enemy
        and current.hp == submitted.hp
        and current.board == submitted.board
    )


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


def read_latest_dialog(log_path: Path) -> str | None:
    """Recover the most recently reported dialogue or non-combat screen."""
    latest = None
    if not log_path.exists():
        return latest
    for match in DIALOG_RE.finditer(
        log_path.read_text(encoding="utf-8", errors="replace")
    ):
        kind = match.group("kind")
        latest = None if kind == "none" else kind
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
            "chapter-aware", "overkill-tier", "shortest-lethal", "max-damage",
        ),
        default="chapter-aware",
    )
    parser.add_argument(
        "--telemetry", type=Path,
        help="append Deluxe attack timing samples as JSONL",
    )
    parser.add_argument(
        "--timer-state", type=Path, default=DEFAULT_TIMER_STATE,
        help="persistent chapter timer JSON created by new-run",
    )
    parser.add_argument(
        "--delay", type=float, default=0.10,
        help="delay between tile clicks; retries increase this automatically",
    )
    parser.add_argument("--settle", type=float, default=0.8)
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
    active_dialog = (
        latest_dialog if latest_dialog in {"conversation", "levelup"} else None
    )
    deluxe_state = None
    if args.layout == "deluxe" and log_path.exists():
        deluxe_state = parse_state(
            log_path.read_text(encoding="utf-8", errors="replace")
        )
    if done:
        label = f"Chapter {chapter}" if chapter is not None else "Current chapter"
        print(f"{label} is already complete.", flush=True)
        return

    controller = X11Keyboard(args.title, args.layout)
    submitted_board = None
    submitted_sequence = None
    submitted_at = None
    submitted_candidate: Candidate | None = None
    submitted_state: DeluxeState | None = None
    submitted_word: str | None = None
    submitted_path: tuple[int, ...] | None = None
    input_confirmed = True
    input_attempts = 0
    input_confirm_at = float("inf")
    handled_dialogs: set[int] = set()
    tutorial_play_submitted = False
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
    boss_reset_state: DeluxeState | None = None
    boss_reset_dialog_ready = False
    pending_stun_heal_hp: float | None = None
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
    attacks = 0
    scrambles = 0
    deadline = time.monotonic() + args.timeout
    ready_at = time.monotonic() + args.ready_delay if ready else float("inf")

    # Open after seeding and seek to EOF: old boards establish current state but
    # are not replayed as a sequence.
    state_buffer = ""
    with log_path.open("r", encoding="utf-8", errors="replace") as log:
        log.seek(0, os.SEEK_END)
        # Close the seed-to-tail race: a non-combat event can arrive after
        # read_seed() but before this cursor is established.
        startup_text = log_path.read_text(encoding="utf-8", errors="replace")
        refreshed_dialog = read_latest_dialog(log_path)
        if refreshed_dialog == "treasure":
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
                    effective_strategy = strategy_for_state(
                        deluxe_state, args.strategy, chapter
                    )
                    effective_strategy = boss_finish_strategy(
                        deluxe_state, effective_strategy, ranked
                    )
                    selected, alternatives = choose(ranked, effective_strategy)
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
                        print(
                            f"  Sphinx answer {riddle_answer} is not playable; "
                            "scrambling instead of submitting a wrong word.",
                            flush=True,
                        )
                        scrambles += 1
                        controller.scramble(args.delay)
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
                attacks += 1
                print(
                    f"Attack {attacks}: {board} -> {word.upper()} "
                    f"({damage:.2f} estimated damage)",
                    flush=True,
                )
                if (
                    args.layout == "deluxe" and deluxe_state is not None
                    and should_use_health_potion(deluxe_state, selected)
                ):
                    # Ordinary fights only heal before a nonlethal turn below
                    # four hearts. Continuous gauntlets retain full healing.
                    controller.use_health_potion(max(0.8, args.delay))
                if (
                    args.layout == "deluxe" and deluxe_state is not None
                    and should_use_purification_potion(deluxe_state)
                ):
                    # Petrify can end an encounter with Lex still at full
                    # health. Cleanse it before submitting the next word.
                    controller.use_purification_potion(max(0.8, args.delay))
                controller.play_word(board, word, args.delay, args.settle, path)
                submitted_board = board
                submitted_word = word
                submitted_path = path
                input_confirmed = False
                input_attempts = 1
                input_confirm_at = time.monotonic() + args.input_confirm_timeout
                if deluxe_state is not None:
                    submitted_sequence = deluxe_state.sequence
                    submitted_at = time.monotonic()
                    submitted_candidate = selected
                    submitted_state = deluxe_state
                ready = False
                deadline = time.monotonic() + args.timeout

            line = log.readline()
            if not line:
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
                    args.layout == "deluxe" and args.auto_dialog and not ready
                    and blocked_screen is None
                    and (
                        boss_reset_state is None
                        or (
                            boss_reset_dialog_ready
                            and active_dialog is not None
                        )
                    )
                    and time.monotonic() >= dialog_probe_at
                ):
                    dialog_probe_count += 1
                    probe_kind = active_dialog or "conversation"
                    print(
                        f"BOARD still blocked without READY; {probe_kind} probe "
                        f"{dialog_probe_count}.",
                        flush=True,
                    )
                    movie_key = (
                        encounter_key(submitted_state)
                        if submitted_state is not None else None
                    )
                    if (
                        should_confirm_book_movie_skip(
                            submitted_state, dialog_probe_count, chapter
                        )
                        and movie_key not in movie_skip_confirmed
                    ):
                        assert movie_key is not None
                        movie_skip_confirmed.add(movie_key)
                        print(
                            "Confirming inter-book movie skip after prolonged "
                            "Chapter 10 transition.",
                            flush=True,
                        )
                        controller.confirm_quit_to_main_menu(args.delay)
                    else:
                        controller.advance_dialog(probe_kind, args.delay)
                    dialog_probe_at = time.monotonic() + args.dialog_probe_interval
                if (
                    not input_confirmed
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
            stunned_event = PLAYER_STUNNED_RE.search(line)
            if stunned_event and stunned_event.group("active") == "1":
                live_hp = (
                    float(stunned_event.group("hp"))
                    if stunned_event.group("hp") is not None
                    else (deluxe_state.player_hp if deluxe_state is not None else -1)
                )
                live_max_hp = (
                    float(stunned_event.group("max_hp"))
                    if stunned_event.group("max_hp") is not None
                    else (
                        deluxe_state.player_max_hp
                        if deluxe_state is not None else -1
                    )
                )
                live_potion = (
                    stunned_event.group("health_potion") == "1"
                    if stunned_event.group("health_potion") is not None
                    else bool(
                        deluxe_state is not None
                        and deluxe_state.health_potion_available
                    )
                )
                if (
                    live_potion and 0 < live_hp <= min(4.0, live_max_hp)
                    and live_hp < live_max_hp
                ):
                    pending_stun_heal_hp = live_hp
                print(
                    "Lua confirmed Lex is stunned; clicking a tile to skip the animation.",
                    flush=True,
                )
                controller.click_tile(0, args.delay)
            elif (
                stunned_event and stunned_event.group("active") == "0"
                and pending_stun_heal_hp is not None
            ):
                print(
                    f"Stun ended with Lex at {pending_stun_heal_hp:g} hearts; "
                    "using the Lua-confirmed health potion now that native UI "
                    "control returned.",
                    flush=True,
                )
                controller.use_health_potion(args.delay)
                pending_stun_heal_hp = None
            if timer_state is not None and process_timer_line(
                timer_state, line, time.time()
            ):
                save_timer_state(args.timer_state, timer_state)
                timed = timer_state["current"]
                print(
                    f"Timer entered Book {timed['book']} Chapter "
                    f"{timed['chapter']}.",
                    flush=True,
                )
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
            dialog = DIALOG_RE.search(line)
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
            elif dialog:
                dialog_sequence = int(dialog.group("sequence"))
                kind = dialog.group("kind")
                active_dialog = kind
                chapter_enter_pending = False
                chapter_enter_at = float("inf")
                # READY immediately before a level-up/conversation can
                # describe the board that is about to transition. Require Lua
                # to publish a fresh stable READY after the overlay.
                ready = False
                input_confirm_at = float("inf")
                if not args.auto_dialog:
                    continue
                if dialog_sequence not in handled_dialogs:
                    handled_dialogs.add(dialog_sequence)
                    if boss_reset_state is not None and not boss_reset_dialog_ready:
                        print(
                            f"Holding Lua-confirmed {kind} dialogue during "
                            "pending boss reset.",
                            flush=True,
                        )
                        continue
                    print(
                        f"Advancing Lua-confirmed {kind} dialogue "
                        f"{dialog_sequence}.",
                        flush=True,
                    )
                    controller.advance_dialog(kind, args.delay)
                    dialog_probe_at = (
                        time.monotonic() + args.dialog_probe_interval
                    )
            if "User clicked ATTACK" in line:
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
                and is_chapter_boss_defeat(submitted_state)
                and encounter_key(submitted_state) not in reset_encounters
                and boss_reset_state is None
            ):
                print(
                    f"Lua confirmed {zero_health_event.group('enemy')} reached zero HP; "
                    "waiting for Lua-confirmed reset-ready state.",
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
                print(
                    f"Lua confirmed {reset_ready_event.group('enemy')} death animation "
                    "settled; waiting for its post-defeat overlay to close.",
                    flush=True,
                )
                boss_reset_dialog_ready = True
                if active_dialog is not None:
                    dialog_probe_at = (
                        time.monotonic() + args.dialog_probe_interval
                    )
                deadline = time.monotonic() + args.timeout
            defeated_event = DEFEATED_RE.search(line)
            if defeated_event and args.auto_menu_reset:
                reset_reason = post_victory_reset_reason(
                    submitted_state, reset_encounters, chapter
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
                    dialog_probe_at = float("inf")
                    dialog_probe_count = 0
                    if (
                        args.layout == "deluxe" and submitted_at is not None
                        and submitted_candidate is not None and submitted_state is not None
                        and deluxe_state is not None
                    ):
                        sample = {
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
