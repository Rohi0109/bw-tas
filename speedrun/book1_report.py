#!/usr/bin/env python3
"""Diagnose Book 1 TAS splits against the supplied human WR."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from book1_optimizer import TELEMETRY_SCHEMA_VERSION
from run_timer import (
    DEFAULT_STATE, DEFAULT_TAS_BEST, DEFAULT_WR_SPLITS, format_delta,
    format_duration,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TELEMETRY = ROOT / "runtime/deluxe-modded/tas-timing.jsonl"


def load_json(path: Path, default: dict) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def human_segments(wr: dict) -> dict[str, float]:
    result = {}
    previous = 0.0
    for book in range(1, 4):
        for chapter in range(1, 11):
            key = f"{book}.{chapter}"
            cumulative = wr.get("chapters", {}).get(key)
            if cumulative is None:
                continue
            result[key] = float(cumulative) - previous
            previous = float(cumulative)
    return result


def load_samples(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("schema_version") == TELEMETRY_SCHEMA_VERSION:
            rows.append(row)
    return rows


def classify_split(row: dict, wr_segment: float | None) -> tuple[bool, list[str]]:
    issues = list(row.get("issues", []))
    elapsed = float(row["elapsed"])
    # This only catches unmistakable abandoned/manual pauses. Smaller delays
    # remain visible and require explicit runner issues rather than guesswork.
    if wr_segment is not None and elapsed > wr_segment * 3:
        issues.append("elapsed-over-3x-wr")
    return not issues and bool(row.get("clean", True)), issues


def build_report(timer: dict, wr: dict, best: dict, samples: list[dict]) -> str:
    segments = human_segments(wr)
    run_id = timer.get("started_at_iso")
    by_chapter: dict[str, list[dict]] = defaultdict(list)
    for sample in samples:
        if sample.get("run_id") == run_id:
            by_chapter[f"{sample['book']}.{sample['chapter']}"] .append(sample)

    current_rows = {
        f"{row['book']}.{row['chapter']}": row
        for row in timer.get("splits", [])
    }
    lines = [
        "Book 1 optimization report",
        f"Run: {run_id or 'legacy/unknown'}",
        "",
        "Ch   TAS segment   Human WR   Delta    Input  Resolve   Other  Attacks  Status",
    ]
    cumulative_gap = 0.0
    for chapter in range(1, 11):
        key = f"1.{chapter}"
        elapsed_value = best.get("segments", {}).get(key)
        if elapsed_value is None:
            continue
        elapsed = float(elapsed_value)
        wr_segment = segments.get(key)
        current = current_rows.get(key, {"elapsed": elapsed})
        clean, issues = classify_split(
            {**current, "elapsed": elapsed}, wr_segment
        )
        chapter_samples = by_chapter.get(key, [])
        combat = sum(
            float(sample["timing"]["ready_seconds"])
            for sample in chapter_samples
        )
        input_time = sum(
            float(sample["timing"].get("input_seconds") or 0.0)
            for sample in chapter_samples
        )
        resolution = max(0.0, combat - input_time)
        other = max(0.0, elapsed - combat)
        delta = elapsed - wr_segment if wr_segment is not None else 0.0
        if wr_segment is not None:
            cumulative_gap += delta
        status = "clean" if clean else "invalid:" + ",".join(issues)
        lines.append(
            f"{key:<4} {format_duration(elapsed):>11}   "
            f"{format_duration(wr_segment or 0):>8}   "
            f"{format_delta(delta):>6}   {format_duration(input_time):>5}  "
            f"{format_duration(resolution):>7}   {format_duration(other):>5}  "
            f"{len(chapter_samples):>7}  {status}"
        )
    lines.extend((
        "",
        f"Completed cumulative gap: {format_delta(cumulative_gap)}",
        "TAS-best entries marked invalid are excluded from recommendations.",
    ))
    lines.append(
        f"Schema-v2 samples for this run: {sum(map(len, by_chapter.values()))}. "
        "Live lookahead requires "
        "at least two recorded actions for the same state."
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timer", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--wr", type=Path, default=DEFAULT_WR_SPLITS)
    parser.add_argument("--best", type=Path, default=DEFAULT_TAS_BEST)
    parser.add_argument("--telemetry", type=Path, default=DEFAULT_TELEMETRY)
    args = parser.parse_args()
    timer = load_json(args.timer, {"splits": []})
    wr = load_json(args.wr, {"chapters": {}})
    best = load_json(args.best, {"segments": {}})
    print(build_report(timer, wr, best, load_samples(args.telemetry)))


if __name__ == "__main__":
    main()
