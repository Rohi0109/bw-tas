#!/usr/bin/env python3
"""Explicit Deluxe main-menu transitions used by the TAS route controller."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from live_runner import X11Keyboard


@dataclass(frozen=True)
class MenuTiming:
    after_battle_menu: float = 0.35
    after_quit_prompt: float = 1.00
    after_quit: float = 1.10
    after_adventure: float = 1.25
    after_enter: float = 1.50


def start_from_main_menu(
    controller: X11Keyboard,
    timing: MenuTiming,
    *,
    enter_chapter: bool = False,
) -> None:
    """Resume Adventure, optionally entering from a chapter-map screen."""
    controller.start_adventure(timing.after_adventure)
    if enter_chapter:
        controller.enter_chapter(timing.after_enter)


def reset_from_battle(
    controller: X11Keyboard,
    timing: MenuTiming,
    *,
    enter_chapter: bool = False,
) -> None:
    """Perform the WR menu-exit/re-entry sequence from an active battle."""
    controller.open_battle_menu(timing.after_battle_menu)
    controller.quit_to_main_menu(timing.after_quit_prompt)
    controller.confirm_quit_to_main_menu(timing.after_quit)
    start_from_main_menu(controller, timing, enter_chapter=enter_chapter)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Drive an explicit Bookworm Adventures Deluxe menu transition"
    )
    parser.add_argument("action", choices=("start", "reset"))
    parser.add_argument("--title", default="Bookworm Adventures Deluxe")
    parser.add_argument(
        "--enter-chapter", action="store_true",
        help="click Enter after Adventure for a verified chapter-map transition",
    )
    parser.add_argument(
        "--countdown", type=float, default=2.0,
        help="seconds to inspect the game screen before the first click",
    )
    args = parser.parse_args()

    if args.countdown > 0:
        print(
            f"Starting menu action {args.action!r} in {args.countdown:g}s; "
            "leave the Deluxe window unobstructed.",
            flush=True,
        )
        time.sleep(args.countdown)

    controller = X11Keyboard(args.title, "deluxe")
    timing = MenuTiming()
    if args.action == "start":
        start_from_main_menu(
            controller, timing, enter_chapter=args.enter_chapter
        )
    else:
        reset_from_battle(
            controller, timing, enter_chapter=args.enter_chapter
        )
    print(f"Menu action {args.action!r} complete.", flush=True)


if __name__ == "__main__":
    main()
