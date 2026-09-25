#!/usr/bin/env python3
"""Safely recreate the designated Deluxe TAS profile for a fresh run."""

from __future__ import annotations

import argparse
import fcntl
import re
import time
from pathlib import Path

from x11_controller import X11Keyboard
from run_timer import (
    DEFAULT_STATE as DEFAULT_TIMER_STATE, record_chapter, save_run_history,
    save_state, start_timer,
)


ROOT = Path(__file__).resolve().parents[1]
PREFIX = ROOT / "runtime/wineprefix"
USERS = PREFIX / "drive_c/ProgramData/PopCap Games/WinBAD/users"
USER_REG = PREFIX / "user.reg"
LUA_LOG = ROOT / "runtime/deluxe-modded/lua.log"
RUNNER_LOCK = ROOT / "runtime/diagnostics/tas-runner.lock"
LUA_WAIT_MARKER = "Program in waiting. Type go() or press F5 to continue execution."
LAST_USER_RE = re.compile(r'^"LastUser"="(?P<name>[^"]+)"$', re.MULTILINE)
INTRO_DIALOG_PULSE_RE = re.compile(
    r"AUTOMATION_DIALOG_PULSE=convpanel\|\d+\|\d+\|E"
)
PLAY_TUTORIAL_MARKER = "AUTOMATION_PLAY_TUTORIAL="


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


def log_suffix_contains(path: Path, offset: int, marker: str) -> bool:
    if not path.exists():
        return False
    if path.stat().st_size < offset:
        offset = 0
    with path.open("r", encoding="utf-8", errors="replace") as log:
        log.seek(offset)
        return marker in log.read()


def skip_intro_until_chapter(
    controller: X11Keyboard, log_path: Path, offset: int,
    timeout: float = 8.0,
) -> None:
    """Pulse only the two intro controls until Lua proves chapter startup."""
    def chapter_started() -> bool:
        return any(
            log_suffix_contains(log_path, offset, marker)
            for marker in ("Book:StartGame called", "AUTOMATION_BOARD=")
        )

    deadline = time.monotonic() + timeout
    wait_recoveries = 0
    time.sleep(0.35)
    while time.monotonic() < deadline:
        if chapter_started():
            return
        if log_suffix_contains(log_path, offset, LUA_WAIT_MARKER):
            if wait_recoveries >= 3:
                raise RuntimeError(
                    "Lua runtime remained paused after 3 F5 recovery attempts"
                )
            wait_recoveries += 1
            print(
                f"Fresh-run Lua wait detected; resuming with F5 "
                f"({wait_recoveries}/3).",
                flush=True,
            )
            # Advance past the handled marker before F5 so a new marker or
            # chapter event emitted by the resumed VM remains visible.
            offset = log_path.stat().st_size
            controller.resume_lua_runtime(0.15)
            continue
        controller.skip_intro(0.08)
        if chapter_started():
            return
        controller.confirm_skip_intro(0.08)
    raise RuntimeError("Timed out waiting for intro confirmation to start Chapter 1")


def bridge_runner_startup_dialogue(
    controller: X11Keyboard, log_path: Path, offset: int,
    timeout: float = 0.75,
) -> None:
    """Advance confirmed Chapter 1 dialogue while the TAS process starts next.

    The shell must start a second Python process after new-run exits. Covering
    that otherwise idle handoff here is safe only for convpanel telemetry; the
    PLAY tutorial has coordinate-specific ownership and ends the bridge.
    """
    deadline = time.monotonic() + timeout
    cursor = offset
    while time.monotonic() < deadline:
        if not log_path.exists():
            time.sleep(0.005)
            continue
        if log_path.stat().st_size < cursor:
            cursor = 0
        with log_path.open("r", encoding="utf-8", errors="replace") as log:
            log.seek(cursor)
            text = log.read()
            cursor = log.tell()
        for line in text.splitlines():
            if PLAY_TUTORIAL_MARKER in line:
                return
            if INTRO_DIALOG_PULSE_RE.search(line):
                controller.advance_dialog("convpanel", 0.01)
        time.sleep(0.005)


def recreate_profile(
    controller: X11Keyboard,
    name: str,
    *,
    from_select_user: bool = False,
    skip_intro: bool = True,
    timer_path: Path | None = None,
    startup_bridge: bool = True,
    log_path: Path = LUA_LOG,
) -> int:
    active = last_user()
    if active.casefold() != name.casefold():
        raise RuntimeError(
            f"Refusing to delete {name!r}: Deluxe LastUser is {active!r}"
        )
    original = profile_path(name)
    protected = {
        path: path.read_bytes() for path in USERS.glob("*.bwa") if path != original
    }

    for delete_attempt in range(2):
        if not from_select_user or delete_attempt:
            controller.change_user(0.7)
        controller.delete_selected_user(0.4)
        controller.confirm_delete_user(0.7)
        try:
            wait_for_profile(name, present=False)
            break
        except RuntimeError:
            if delete_attempt:
                raise
            print(
                "Profile delete was not accepted during launch; retrying "
                "the menu sequence once.",
                flush=True,
            )

    for path, contents in protected.items():
        if not path.exists() or path.read_bytes() != contents:
            path.write_bytes(contents)
            raise RuntimeError(
                f"A protected profile changed while deleting {name!r}; restored {path.name}"
            )

    controller.create_new_user(0.4)
    log_offset = log_path.stat().st_size if log_path.exists() else 0
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
        save_run_history(timer)
        print(f"Run timer started: {timer['started_at_iso']}", flush=True)
    if skip_intro:
        # These pre-Lua screens have no engine update hook. Alternate only
        # their two safe controls and stop on the first new chapter-start line.
        skip_intro_until_chapter(controller, log_path, log_offset)
        if startup_bridge:
            bridge_runner_startup_dialogue(
                controller, log_path,
                log_path.stat().st_size if log_path.exists() else 0,
            )
    return log_offset


def main() -> None:
    parser = argparse.ArgumentParser(description="Recreate a fresh Deluxe TAS user")
    parser.add_argument(
        "--profile",
        help="profile to recreate (defaults to Deluxe's active LastUser)",
    )
    parser.add_argument(
        "--from-select-user", action="store_true",
        help="the game is already on Select a User with LastUser selected",
    )
    parser.add_argument(
        "--skip-intro", action=argparse.BooleanOptionalAction, default=True,
    )
    parser.add_argument("--timer", type=Path, default=DEFAULT_TIMER_STATE)
    args = parser.parse_args()

    RUNNER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with RUNNER_LOCK.open("a+", encoding="utf-8") as input_lock:
        try:
            fcntl.flock(input_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "TAS input is already active; stop the runner before new-run"
            ) from error
        controller = X11Keyboard("Bookworm Adventures Deluxe", "deluxe")
        profile = args.profile or last_user()
        recreate_profile(
            controller,
            profile,
            from_select_user=args.from_select_user,
            skip_intro=args.skip_intro,
            timer_path=args.timer,
        )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(f"new-run stopped: {error}")
