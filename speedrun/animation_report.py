"""Summarize measured combat timing by visible attack and gem animation class."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from deluxe_optimizer import attack_animation_class


def animation_groups(path: Path) -> list[dict]:
    groups: dict[tuple, list[float]] = defaultdict(list)
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
            if row.get("record_type") != "attack-to-zero-health":
                continue
            action = row["action"]
            timing = row["timing"]
            seconds = float(timing["attack_to_zero_health_seconds"])
            letters = len(action["word"])
            gem_types = tuple(action.get("gem_types", ()))
            key = (
                action.get("animation_class", attack_animation_class(letters)),
                action.get("tier"),
                "diamond" in gem_types,
                bool(action.get("lethal")),
                True,
            )
            if row.get("clean", False) and seconds >= 0:
                groups[key].append(seconds)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    result = []
    for key, values in sorted(groups.items(), key=lambda item: str(item[0])):
        animation, tier, diamond, lethal, killed = key
        result.append({
            "animation_class": animation,
            "reward_tier": tier,
            "uses_diamond": diamond,
            "predicted_lethal": lethal,
            "kill_confirmed": killed,
            "samples": len(values),
            "minimum_seconds": min(values),
            "median_seconds": statistics.median(values),
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path", nargs="?", type=Path,
        default=Path(__file__).resolve().parents[1]
        / "runtime/deluxe-modded/tas-timing.jsonl",
    )
    args = parser.parse_args()
    print(json.dumps(animation_groups(args.path), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
