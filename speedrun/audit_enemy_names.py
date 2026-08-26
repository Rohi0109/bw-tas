"""Report distinct live Deluxe enemy names that do not match the static roster."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from deluxe_optimizer import DeluxeState, load_chapter1_hp_map, validate_chapter1_state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", nargs="?", type=Path,
                        default=Path("runtime/deluxe-modded/lua.log"))
    args = parser.parse_args()
    text = args.log.read_text(encoding="utf-8", errors="replace")
    names = {
        int(match.group(1)): match.group(2)
        for match in re.finditer(r"AUTOMATION_ENEMY=(\d+)\|([^|]+)\|E", text)
    }
    max_hp = {
        int(match.group(1)): float(match.group(2))
        for match in re.finditer(
            r"AUTOMATION_HEALTH=(\d+)\|[^|]+\|([^|]+)\|", text
        )
    }
    books = {
        int(match.group(1)): int(match.group(2))
        for match in re.finditer(
            r"AUTOMATION_CONTEXT=(\d+)\|(-?\d+)\|", text
        )
    }
    hp_map = load_chapter1_hp_map()
    warnings = set()
    for sequence, enemy in names.items():
        if sequence not in max_hp:
            continue
        state = DeluxeState(
            sequence, "AAAA/AAAA/AAAA/AAAA", ("none",) * 16, (0.0,) * 16,
            books.get(sequence, -1), -1, -1, enemy,
            max_hp[sequence], max_hp[sequence], 0.0,
            frozenset(), (),
        )
        warning = validate_chapter1_state(state, hp_map)
        if warning:
            warnings.add(warning)
    if warnings:
        for warning in sorted(warnings):
            print(warning)
        raise SystemExit(1)
    print(f"All {len(set(names.values()))} distinct live enemy names match the roster.")


if __name__ == "__main__":
    main()
