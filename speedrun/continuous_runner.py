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
    load_metal_words, parse_state, validate_chapter1_state,
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
SPHINX_ANSWERS = {
    "Sphinx (Riddle 1 of 5)": "SKY",
    "Sphinx (Riddle 2 of 5)": "WALL",
    "Sphinx (Riddle 3 of 5)": "FIST",
    "Sphinx (Riddle 4 of 5)": "TRUTH",
    "Sphinx (Last Riddle)": "WATER",
}


def sphinx_candidate(
    enemy: str, ranked: list[Candidate]
) -> tuple[Candidate | None, str | None]:
    """Return the fixed correct riddle answer when it is playable."""
    answer = SPHINX_ANSWERS.get(enemy)
    if answer is None:
        return None, None
    return next((candidate for candidate in ranked if candidate.word == answer), None), answer


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
        choices=("overkill-tier", "shortest-lethal", "max-damage"),
        default="overkill-tier",
    )
    parser.add_argument(
        "--telemetry", type=Path,
        help="append Deluxe attack timing samples as JSONL",
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
    parser.add_argument("--max-attacks", type=int, default=100)
    parser.add_argument(
        "--max-scrambles", type=int, default=10,
        help="stop after this many no-word Scramble fallbacks",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    log_path = args.log.resolve()
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
    dialog_probe_at = (
        time.monotonic() + args.dialog_stall_delay
        if args.layout == "deluxe" and not ready and blocked_screen is None
        else float("inf")
    )
    dialog_probe_count = 0
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
                    ranked = candidates(
                        deluxe_state, deluxe_words, metal_words, args.delay
                    )
                    if not ranked:
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
                    selected, alternatives = choose(ranked, args.strategy)
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
                            f"  Sphinx warning: expected answer {riddle_answer} is "
                            "not playable; falling back to normal ranking.",
                            flush=True,
                        )
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
                if (
                    args.layout == "deluxe" and args.auto_dialog and not ready
                    and blocked_screen is None
                    and time.monotonic() >= dialog_probe_at
                ):
                    dialog_probe_count += 1
                    probe_kind = active_dialog or "conversation"
                    print(
                        f"BOARD still blocked without READY; {probe_kind} probe "
                        f"{dialog_probe_count}.",
                        flush=True,
                    )
                    controller.advance_dialog(probe_kind, args.delay)
                    dialog_probe_at = time.monotonic() + args.dialog_probe_interval
                if (
                    not input_confirmed
                    and active_dialog is None
                    and blocked_screen is None
                    and time.monotonic() >= input_confirm_at
                ):
                    if input_attempts >= args.max_input_attempts:
                        raise RuntimeError(
                            f"Game did not acknowledge {submitted_word.upper()} after "
                            f"{input_attempts} selection attempts"
                        )
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
            dialog = DIALOG_RE.search(line)
            if dialog and dialog.group("kind") == "none":
                was_blocked = blocked_screen is not None
                blocked_screen = None
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
            elif dialog and dialog.group("kind") == "treasure":
                blocked_screen = "treasure"
                active_dialog = None
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
            elif dialog:
                dialog_sequence = int(dialog.group("sequence"))
                kind = dialog.group("kind")
                active_dialog = kind
                # READY immediately before a level-up/conversation can
                # describe the board that is about to transition. Require Lua
                # to publish a fresh stable READY after the overlay.
                ready = False
                input_confirm_at = float("inf")
                if not args.auto_dialog:
                    continue
                if dialog_sequence not in handled_dialogs:
                    handled_dialogs.add(dialog_sequence)
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
            if args.layout == "deluxe":
                state_buffer = (state_buffer + "\n" + line)[-32768:]
            new_state = parse_state(state_buffer) if args.layout == "deluxe" else None
            if new_state is not None and (
                deluxe_state is None or new_state.sequence >= deluxe_state.sequence
            ):
                deluxe_state = new_state
                board = new_state.board
            match = CHAPTER_RE.search(line)
            if match:
                chapter = int(match.group("chapter"))
                submitted_board = None
                ready = False
                print(f"Entered Chapter {chapter}.", flush=True)
            for event in BOARD_EVENT_RE.finditer(line):
                board = event.group("board")
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
