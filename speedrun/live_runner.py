"""Bridge the copied speedrun solver to the running Wine game.

The board format is four rows separated by slashes, e.g. ABCD/EFGH/IJKL/MNOP.
The runner maps the chosen word back to tile occurrences, clicks them, and then
clicks Attack.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from board.parse_board import parse_board
from board.solve_board import setup, solve_board
from calculate_damage.set_modifiers import Modifiers


# Compatibility exports; new code imports x11_controller directly.
from x11_controller import X11Keyboard, XClientMessageData, XClientMessageEvent, XEvent


def best_word(board_text: str) -> tuple[str, float]:
    root = Path(__file__).resolve().parent
    word_dict = json.loads((root / "word_dict.json").read_text(encoding="utf-8"))
    result = solve_board(
        parse_board(board_text), word_dict, setup(word_dict), Modifiers()
    )
    if result is None:
        raise RuntimeError("The solver found no playable word")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve and play one live BWA board")
    parser.add_argument("--board", required=True, help="ABCD/EFGH/IJKL/MNOP")
    parser.add_argument("--title", default="Bookworm Adventures")
    parser.add_argument("--layout", choices=("web", "deluxe"), default="web")
    parser.add_argument("--delay", type=float, default=0.035)
    parser.add_argument("--settle", type=float, default=0.5,
                        help="pause after selecting the word before Attack")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    word, damage = best_word(args.board)
    print(f"{word.upper()} ({damage:.2f} estimated damage)")
    if not args.dry_run:
        X11Keyboard(args.title, args.layout).play_word(
            args.board, word, args.delay, args.settle
        )


if __name__ == "__main__":
    main()
