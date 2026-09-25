"""Command-line settings and validation; no input or profile changes."""

import argparse
import os
from pathlib import Path

from run_timer import DEFAULT_STATE as DEFAULT_TIMER_STATE


def read_settings() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Follow lua.log and play each newly generated board"
    )
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument('--menu-reset-trace', type=Path,
                        help='append diagnostic reset-cycle JSONL without changing reset timing')
    parser.add_argument('--menu-reset-mode', choices=('legacy', 'observed'), default='legacy')
    parser.add_argument("--experiment", action="store_true",
                        help="record a separate session/build identity and disable race timing")
    parser.add_argument("--title", default="Bookworm Adventures")
    parser.add_argument("--layout", choices=("web", "deluxe"), default="web")
    parser.add_argument("--new-run", action="store_true",
                        help="preload, then delete/recreate the active Deluxe profile and start TAS")
    parser.add_argument("--profile", help="profile to recreate with --new-run (default: active LastUser)")
    parser.add_argument("--from-select-user", action="store_true",
                        help="with --new-run, start from Select a User instead of the main menu")
    parser.add_argument(
        "--strategy",
        choices=(
            "chapter-aware", "book1-lookahead", "overkill-tier",
            "shortest-lethal", "max-damage", "speed-sapphire",
        ),
        default="chapter-aware",
    )
    parser.add_argument(
        "--telemetry", type=Path,
        help="append Deluxe attack timing samples as JSONL",
    )
    parser.add_argument(
        "--book1-corpus", type=Path,
        help="validated schema-v2 transitions used by book1-lookahead",
    )
    parser.add_argument(
        "--book1-overrides", type=Path,
        help="exact-state JSON decisions for deterministic branch experiments",
    )
    parser.add_argument(
        "--timer-state", type=Path, default=DEFAULT_TIMER_STATE,
        help="persistent chapter timer JSON created by new-run",
    )
    parser.add_argument(
        "--delay", type=float, default=0.08,
        help="delay for non-rack UI actions",
    )
    parser.add_argument(
        "--tile-delay", type=float, default=0.01,
        help="delay between rack tile events (default: 10 ms)",
    )
    parser.add_argument(
        "--settle", type=float, default=0.15,
        help="short guard before Attack; Deluxe still submits during tile animation",
    )
    parser.add_argument(
        "--poll", type=float, default=0.01,
        help="idle telemetry poll interval (default: 10 ms)",
    )
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
        "--auto-menu-reset", action=argparse.BooleanOptionalAction, default=True,
        help="perform verified boss and route-note menu resets (default: enabled)",
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
        "--ready-delay", type=float, default=0.0,
        help="optional guard after Lua confirms tile input is enabled (default: none)",
    )
    parser.add_argument("--max-attacks", type=int, default=1000)
    parser.add_argument(
        "--max-scrambles", type=int, default=10,
        help="stop after this many no-word Scramble fallbacks",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default=os.environ.get("BWA_TAS_LOG_LEVEL", "INFO").upper(),
        help="runner console verbosity (or set BWA_TAS_LOG_LEVEL)",
    )
    parser.add_argument(
        "--log-file", type=Path,
        help="write a complete DEBUG log for later diagnosis",
    )
    args = parser.parse_args()
    if args.menu_reset_mode == 'observed':
        parser.error('observed reset mode is not yet available: native menu-state observations have not been validated; use legacy')
    if args.experiment:
        if args.new_run or args.layout != "deluxe":
            parser.error("--experiment requires Deluxe and does not support --new-run")
        args.timer_state = None
        if args.telemetry is None:
            args.telemetry = args.log.resolve().parent / 'tas-timing.jsonl'
    if args.new_run and args.layout != "deluxe":
        parser.error("--new-run requires --layout deluxe")
    if (args.profile or args.from_select_user) and not args.new_run:
        parser.error("--profile/--from-select-user require --new-run")
    return args
