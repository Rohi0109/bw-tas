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
DEFAULT_WR_SPLITS = ROOT / "human-wr-splits.json"
DEFAULT_TAS_BEST = ROOT / "tas-best-splits.json"
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
    if path.exists():
        update_tas_best(load_state(path))
    now = time.time() if timestamp is None else timestamp
    state = {
        "version": 2,
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
    state["current"] = {
        **key, "started_at": timestamp, "clean": True, "issues": [],
    }
    return True


def mark_current_issue(state: dict, issue: str) -> bool:
    """Mark the active split ineligible for clean TAS-best comparisons."""
    current = state.get("current")
    if current is None:
        return False
    issues = current.setdefault("issues", [])
    if issue not in issues:
        issues.append(issue)
    current["clean"] = False
    return True


def wr_segment_seconds(wr: dict, book: int, chapter: int) -> float | None:
    current = wr.get("chapters", {}).get(f"{book}.{chapter}")
    if current is None:
        return None
    if chapter > 1:
        previous = wr.get("chapters", {}).get(f"{book}.{chapter - 1}")
    elif book > 1:
        previous = wr.get("chapters", {}).get(f"{book - 1}.10")
    else:
        previous = 0.0
    return float(current) - float(previous or 0.0)


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


def format_delta(seconds: float) -> str:
    sign = "+" if seconds >= 0 else "-"
    return f"{sign}{format_duration(abs(seconds))}"


def load_wr_splits(path: Path = DEFAULT_WR_SPLITS) -> dict:
    if not path.exists():
        return {"chapters": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def load_tas_best(path: Path = DEFAULT_TAS_BEST) -> dict:
    if not path.exists():
        return {"version": 1, "segments": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def update_tas_best(
    state: dict, path: Path = DEFAULT_TAS_BEST,
) -> dict:
    """Persist fastest completed TAS chapter segments across fresh runs."""
    best = load_tas_best(path)
    segments = best.setdefault("segments", {})
    wr = load_wr_splits()
    changed = False
    # Purge only unmistakable abandoned/manual pauses from legacy best data.
    for key, elapsed in list(segments.items()):
        book, chapter = map(int, key.split("."))
        target = wr_segment_seconds(wr, book, chapter)
        if target is not None and elapsed > target * 3:
            del segments[key]
            changed = True
    for row in state.get("splits", []):
        key = f"{row['book']}.{row['chapter']}"
        elapsed = row["elapsed"]
        target = wr_segment_seconds(wr, row["book"], row["chapter"])
        if not row.get("clean", True) or row.get("issues"):
            continue
        if target is not None and elapsed > target * 3:
            continue
        if key not in segments or elapsed < segments[key]:
            segments[key] = elapsed
            changed = True
    if changed:
        path.write_text(json.dumps(best, indent=2) + "\n", encoding="utf-8")
    return best


def report(
    state: dict, timestamp: float | None = None, wr: dict | None = None,
    tas_best: dict | None = None,
) -> str:
    now = time.time() if timestamp is None else timestamp
    wr = load_wr_splits() if wr is None else wr
    wr_chapters = wr.get("chapters", {})
    tas_best = load_tas_best() if tas_best is None else tas_best
    best_segments = dict(tas_best.get("segments", {}))
    for completed in state.get("splits", []):
        key = f"{completed['book']}.{completed['chapter']}"
        best_segments[key] = min(
            completed["elapsed"], best_segments.get(key, float("inf"))
        )
    end = state.get("finished_at") or now
    rows = list(state.get("splits", []))
    current = state.get("current")
    if current is not None and state.get("finished_at") is None:
        rows.append({**current, "elapsed": end - current["started_at"]})
    lines = [f"Total: {format_duration(end - state['started_at'])}"]
    book_totals: dict[int, float] = {}
    completed_books = {
        row["book"] for row in state.get("splits", []) if row["chapter"] == 10
    }
    cumulative = 0.0
    previous_wr = 0.0
    for row in rows:
        cumulative += row["elapsed"]
        book_totals[row["book"]] = book_totals.get(row["book"], 0) + row["elapsed"]
        suffix = " (running)" if current is not None and row is rows[-1] and not state.get("finished_at") else ""
        wr_cumulative = wr_chapters.get(f"{row['book']}.{row['chapter']}")
        comparison = ""
        tas_segment = best_segments.get(f"{row['book']}.{row['chapter']}")
        if tas_segment is not None:
            comparison += f" | TAS best {format_duration(tas_segment)}"
        if wr_cumulative is not None:
            wr_segment = wr_cumulative - previous_wr
            comparison += (
                f" | WR {format_duration(wr_segment)}"
                f" | chapter {format_delta(row['elapsed'] - wr_segment)}"
                f" | cumulative {format_delta(cumulative - wr_cumulative)}"
            )
            previous_wr = wr_cumulative
        lines.append(
            f"  Book {row['book']} Chapter {row['chapter']}: "
            f"{format_duration(row['elapsed'])}{suffix}{comparison}"
        )
    for book in sorted(book_totals):
        wr_book = wr.get("book_seconds", {}).get(str(book))
        label = "total" if book in completed_books else "progress"
        comparison = ""
        if wr_book is not None:
            comparison = f" | Human WR {format_duration(wr_book)}"
            if book in completed_books:
                comparison += f" | gap {format_delta(book_totals[book] - wr_book)}"
        lines.append(
            f"Book {book} {label}: {format_duration(book_totals[book])}"
            f"{comparison}"
        )
    if wr.get("book_seconds"):
        targets = ", ".join(
            f"Book {book} {format_duration(seconds)}"
            for book, seconds in sorted(
                ((int(book), seconds) for book, seconds in wr["book_seconds"].items())
            )
        )
        lines.append(f"Human WR books: {targets}")
    if wr.get("total_seconds") is not None:
        lines.append(f"Human WR target: {format_duration(wr['total_seconds'])}")
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
                    update_tas_best(state)
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
    parser.add_argument(
        "action", choices=("start", "watch", "report", "finish", "update-best")
    )
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
        update_tas_best(state)
        print(report(state, now))
    elif args.action == "update-best":
        best = update_tas_best(load_state(args.state))
        print(f"Saved {len(best['segments'])} TAS best chapter splits.")
    else:
        print(report(load_state(args.state)))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(f"timer stopped: {error}")
