#!/usr/bin/env python3
"""Safely recreate the designated Deluxe TAS profile for a fresh run."""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

from live_runner import X11Keyboard
from run_timer import (
    DEFAULT_STATE as DEFAULT_TIMER_STATE, record_chapter, save_state, start_timer,
)


ROOT = Path(__file__).resolve().parents[1]
PREFIX = ROOT / "runtime/wineprefix"
USERS = PREFIX / "drive_c/ProgramData/PopCap Games/WinBAD/users"
USER_REG = PREFIX / "user.reg"
LAST_USER_RE = re.compile(r'^"LastUser"="(?P<name>[^"]+)"$', re.MULTILINE)


def last_user(registry: Path = USER_REG) -> str:
    match = LAST_USER_RE.search(registry.read_text(encoding="utf-8", errors="replace"))
    if match is None:
        raise RuntimeError(f"LastUser is missing from {registry}")
    return match.group("name")


def profile_path(name: str, users: Path = USERS) -> Path:
    matches = [path for path in users.glob("*.bwa") if path.stem.casefold() == name.casefold()]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one save named {name!r}, found {[p.name for p in matches]}"
        )
    return matches[0]


def wait_for_profile(name: str, *, present: bool, timeout: float = 3.0) -> Path | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = [
            path for path in USERS.glob("*.bwa")
            if path.stem.casefold() == name.casefold()
        ]
        if bool(matches) == present:
            return matches[0] if matches else None
        time.sleep(0.05)
    condition = "appear" if present else "disappear"
    raise RuntimeError(f"Timed out waiting for profile {name!r} to {condition}")


def recreate_profile(
    controller: X11Keyboard,
    name: str,
    *,
    from_select_user: bool = False,
    skip_intro: bool = True,
    timer_path: Path | None = None,
) -> None:
    active = last_user()
    if active.casefold() != name.casefold():
        raise RuntimeError(
            f"Refusing to delete {name!r}: Deluxe LastUser is {active!r}"
        )
    original = profile_path(name)
    protected = {
        path: path.read_bytes() for path in USERS.glob("*.bwa") if path != original
    }

    if not from_select_user:
        controller.change_user(0.7)
    controller.delete_selected_user(0.4)
    controller.confirm_delete_user(0.7)
    wait_for_profile(name, present=False)

    for path, contents in protected.items():
        if not path.exists() or path.read_bytes() != contents:
            path.write_bytes(contents)
            raise RuntimeError(
                f"A protected profile changed while deleting {name!r}; restored {path.name}"
            )

    controller.create_new_user(0.4)
    confirmed_at = controller.replace_user_name(name, name, 0.08)
    created = wait_for_profile(name, present=True)
    print(f"Created fresh TAS profile: {created}", flush=True)
    if timer_path is not None:
        timer = start_timer(timer_path, timestamp=confirmed_at)
        # Deluxe labels the opening tutorial as chapter -1 in Lua.  A profile
        # created here always begins at Book 1 Chapter 1. Category timing starts
        # on the Return key that confirms this filename.
        record_chapter(timer, 1, 1, timer["started_at"])
        save_state(timer_path, timer)
        print(f"Run timer started: {timer['started_at_iso']}", flush=True)
    if skip_intro:
        time.sleep(2.5)
        # The comic and its confirmation are native UI; Lua telemetry does not
        # begin until BookManager starts the chapter.  Give the confirmation
        # animation a conservative settle instead of racing it.
        controller.skip_intro(1.0)
        controller.confirm_skip_intro(0.8)


def main() -> None:
    parser = argparse.ArgumentParser(description="Recreate a fresh Deluxe TAS user")
    parser.add_argument("--profile", default="Lex10")
    parser.add_argument(
        "--from-select-user", action="store_true",
        help="the game is already on Select a User with LastUser selected",
    )
    parser.add_argument(
        "--skip-intro", action=argparse.BooleanOptionalAction, default=True,
    )
    parser.add_argument("--timer", type=Path, default=DEFAULT_TIMER_STATE)
    args = parser.parse_args()

    controller = X11Keyboard("Bookworm Adventures Deluxe", "deluxe")
    recreate_profile(
        controller,
        args.profile,
        from_select_user=args.from_select_user,
        skip_intro=args.skip_intro,
        timer_path=args.timer,
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(f"new-run stopped: {error}")
