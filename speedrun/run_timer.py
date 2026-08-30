#!/usr/bin/env python3
"""Persistent wall-clock timer and book/chapter split recorder."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from deluxe_optimizer import DISPLAY_NAME_ALIASES


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "runtime/deluxe-modded/run-timer.json"
DEFAULT_LOG = ROOT / "runtime/deluxe-modded/lua.log"
CHAPTER_RE = re.compile(
    r"Book:StartGame called for book Book(?P<book>\d+), chapter (?P<chapter>\d+)"
)
CONTEXT_RE = re.compile(
    r"AUTOMATION_CONTEXT=\d+\|(?P<book>-?\d+)\|(?P<chapter>-?\d+)\|"
)
ENEMY_RE = re.compile(r"AUTOMATION_ENEMY=\d+\|(?P<enemy>[^|]+)\|E")
ROSTER_PATH = ROOT / "BookwormAdventuresModding/bwakit/game/data/enemy_rosters.txt"


def normalize_enemy(name: str) -> str:
    normalized = "".join(
        character for character in name.casefold() if character.isalnum()
    ).removesuffix("boss")
    normalized = {
        "angrymountaingoat": "mountaingoat",
        "angryewe": "ewe",
    }.get(normalized, normalized)
    if normalized.startswith("hydrahead") or normalized == "hydramainhead":
        normalized = "hydra"
    return DISPLAY_NAME_ALIASES.get(normalized, normalized)


def load_enemy_chapters(path: Path = ROSTER_PATH) -> dict[tuple[int, str], int]:
    mapping: dict[tuple[int, str], int] = {}
    book = chapter = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"\s*Chapter (\d+)\.(\d+):", line)
        if heading:
            book, chapter = map(int, heading.groups())
            continue
        enemy = re.match(r"\s*-\s+(.+?)\s*$", line)
        if enemy and book is not None and chapter is not None:
            mapping[(book, normalize_enemy(enemy.group(1)))] = chapter
    return mapping


ENEMY_CHAPTERS = load_enemy_chapters()


def now_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def start_timer(path: Path = DEFAULT_STATE, timestamp: float | None = None) -> dict:
    now = time.time() if timestamp is None else timestamp
    state = {
        "version": 1,
        "started_at": now,
        "started_at_iso": now_iso(now),
        "current": None,
        "live_book": 1,
        "splits": [],
        "finished_at": None,
    }
    save_state(path, state)
    return state


def load_state(path: Path = DEFAULT_STATE) -> dict:
    if not path.exists():
        raise RuntimeError(f"Run timer has not been started: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def record_chapter(state: dict, book: int, chapter: int, timestamp: float) -> bool:
    if book < 1 or chapter < 1:
        return False
    key = {"book": book, "chapter": chapter}
    current = state.get("current")
    if current is not None and all(current[field] == key[field] for field in key):
        return False
    if current is not None:
        state["splits"].append({
            **current,
            "ended_at": timestamp,
            "elapsed": timestamp - current["started_at"],
        })
    state["current"] = {**key, "started_at": timestamp}
    return True


def process_line(state: dict, line: str, timestamp: float) -> bool:
    match = CHAPTER_RE.search(line)
    if match:
        return record_chapter(
            state, int(match.group("book")), int(match.group("chapter")), timestamp
        )
    match = CONTEXT_RE.search(line)
    if match:
        state["live_book"] = int(match.group("book"))
        return record_chapter(
            state, int(match.group("book")), int(match.group("chapter")), timestamp
        )
    match = ENEMY_RE.search(line)
    if match:
        book = int(state.get("live_book", -1))
        chapter = ENEMY_CHAPTERS.get((book, normalize_enemy(match.group("enemy"))))
        return chapter is not None and record_chapter(state, book, chapter, timestamp)
    return False


def format_duration(seconds: float) -> str:
    seconds = max(0, round(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def report(state: dict, timestamp: float | None = None) -> str:
    now = time.time() if timestamp is None else timestamp
    end = state.get("finished_at") or now
    rows = list(state.get("splits", []))
    current = state.get("current")
    if current is not None and state.get("finished_at") is None:
        rows.append({**current, "elapsed": end - current["started_at"]})
    lines = [f"Total: {format_duration(end - state['started_at'])}"]
    book_totals: dict[int, float] = {}
    for row in rows:
        book_totals[row["book"]] = book_totals.get(row["book"], 0) + row["elapsed"]
        suffix = " (running)" if current is not None and row is rows[-1] and not state.get("finished_at") else ""
        lines.append(
            f"  Book {row['book']} Chapter {row['chapter']}: "
            f"{format_duration(row['elapsed'])}{suffix}"
        )
    for book in sorted(book_totals):
        lines.append(f"Book {book} total: {format_duration(book_totals[book])}")
    return "\n".join(lines)


def watch(log_path: Path, state_path: Path, poll: float = 0.1) -> None:
    state = load_state(state_path)
    log = None
    identity = None
    position = 0
    print(f"Timing run from {state['started_at_iso']}; watching {log_path}", flush=True)
    while True:
        if log_path.exists():
            stat = log_path.stat()
            new_identity = (stat.st_dev, stat.st_ino)
            if log is None or new_identity != identity or stat.st_size < position:
                if log is not None:
                    log.close()
                log = log_path.open("r", encoding="utf-8", errors="replace")
                identity = new_identity
                position = 0 if stat.st_size < position else stat.st_size
                log.seek(position)
            line = log.readline()
            if line:
                position = log.tell()
                timestamp = time.time()
                if process_line(state, line, timestamp):
                    save_state(state_path, state)
                    current = state["current"]
                    print(
                        f"Split: Book {current['book']} Chapter {current['chapter']} "
                        f"at {format_duration(timestamp - state['started_at'])}",
                        flush=True,
                    )
                continue
        time.sleep(poll)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "watch", "report", "finish"))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()
    if args.action == "start":
        state = start_timer(args.state)
        print(f"Timer started: {state['started_at_iso']}")
    elif args.action == "watch":
        watch(args.log, args.state)
    elif args.action == "finish":
        state = load_state(args.state)
        now = time.time()
        current = state.get("current")
        if current is not None:
            state["splits"].append({
                **current, "ended_at": now,
                "elapsed": now - current["started_at"],
            })
            state["current"] = None
        state["finished_at"] = now
        save_state(args.state, state)
        print(report(state, now))
    else:
        print(report(load_state(args.state)))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(f"timer stopped: {error}")
