#!/usr/bin/env python3
"""Explicit Deluxe main-menu transitions used by the TAS route controller."""

from __future__ import annotations

import argparse
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from x11_controller import X11Keyboard


@dataclass(frozen=True)
class MenuTiming:
    after_battle_menu: float = 0.03
    after_quit_prompt: float = 0.03
    after_quit: float = 0.08
    after_adventure: float = 1.25
    after_enter: float = 1.50


def event_driven_reset_timing() -> MenuTiming:
    """Use native telemetry, rather than a post-Adventure blind wait.

    Deluxe's battle menu, quit prompt, and title menu are native screens that
    do not run our Lua hooks, so their inter-click guards remain necessary.
    Adventure hands control back to BookManager, whose chapter-map telemetry
    is authoritative; sleeping after that click only delays consumption of an
    event that may already have arrived.
    """
    return MenuTiming(after_adventure=0.0)


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
    telemetry_log: Path | None = None,
    trace=None,
) -> None:
    """Perform the WR menu-exit/re-entry sequence from an active battle."""
    boundary = os.path.getsize(telemetry_log) if telemetry_log is not None else 0
    if trace:
        trace.begin()
    def event(stage, **fields):
        if trace:
            trace.event(stage, **fields)
    def action(sent_stage, returned_stage, method, delay):
        event(sent_stage, configured_sleep=delay)
        getattr(controller, method)(delay)
        fields = {
            'configured_sleep': delay,
            'input_flush_monotonic': getattr(
                controller, 'last_input_flush_at', None,
            ),
        }
        event(returned_stage, **fields)
    action(
        'battle_menu_action_sent', 'battle_menu_action_returned',
        'open_battle_menu', timing.after_battle_menu,
    )
    action(
        'quit_action_sent', 'quit_action_returned',
        'quit_to_main_menu', timing.after_quit_prompt,
    )
    if telemetry_log is not None:
        # The menu can take a variable number of frames to own input. Retry its
        # harmless Quit hotspot until LuaApp confirms that the yes/no dialog
        # exists. Fall back after 0.7 s for builds that suspend combat Lua as
        # soon as the native menu opens.
        deadline = time.monotonic() + 0.7
        confirmed = False
        retries = 0
        observation_receipt = None
        event('dialog_ack_wait_started')
        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            try:
                with telemetry_log.open("rb") as stream:
                    stream.seek(boundary)
                    confirmed = re.search(
                        rb"AUTOMATION_NATIVE_DIALOG=1\|E", stream.read()
                    ) is not None
            except FileNotFoundError:
                pass
            if confirmed:
                observation_receipt = now
                break
            controller.quit_to_main_menu(0.0)
            retries += 1
            time.sleep(0.01)
        fields = {'retries': retries}
        if observation_receipt is not None:
            event(
                'dialog_observation_received',
                observation_receipt_monotonic=observation_receipt,
            )
        event('dialog_acknowledged' if confirmed else 'dialog_ack_timeout', **fields)
    action(
        'confirm_quit_action_sent', 'confirm_quit_action_returned',
        'confirm_quit_to_main_menu', timing.after_quit,
    )
    event('adventure_action_sent')
    start_from_main_menu(controller, timing, enter_chapter=enter_chapter)
    event('reset_input_sequence_returned')


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
