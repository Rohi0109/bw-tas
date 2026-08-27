"""Bridge the copied speedrun solver to the running Wine game.

The board format is four rows separated by slashes, e.g. ABCD/EFGH/IJKL/MNOP.
The runner maps the chosen word back to tile occurrences, clicks them, and then
clicks Attack.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import time
from pathlib import Path

from board.parse_board import parse_board
from board.solve_board import setup, solve_board
from calculate_damage.set_modifiers import Modifiers


class X11Keyboard:
    def __init__(self, title: str, layout: str = "web") -> None:
        self.layout = layout
        self.x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self.xtst = ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x11.XQueryTree.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self.x11.XFetchName.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_char_p),
        ]
        self.x11.XFree.argtypes = [ctypes.c_void_p]
        self.x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x11.XKeysymToKeycode.restype = ctypes.c_uint
        self.x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.x11.XStringToKeysym.restype = ctypes.c_ulong
        self.xtst.XTestFakeKeyEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.x11.XGetGeometry.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self.x11.XTranslateCoordinates.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
        ]
        self.xtst.XTestFakeMotionEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.xtst.XTestFakeButtonEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong,
        ]
        self.display = self.x11.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("Could not open the X11 display")
        self.window = self._find_window(title.casefold())
        if not self.window:
            raise RuntimeError(f"No visible window title contains {title!r}")
        self.frame = self._top_level(self.window)

    def _children(self, window: int) -> list[int]:
        root = ctypes.c_ulong()
        parent = ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        if not self.x11.XQueryTree(
            self.display,
            window,
            ctypes.byref(root),
            ctypes.byref(parent),
            ctypes.byref(children),
            ctypes.byref(count),
        ):
            return []
        result = [children[i] for i in range(count.value)]
        if children:
            self.x11.XFree(children)
        return result

    def _parent(self, window: int) -> int:
        root = ctypes.c_ulong()
        parent = ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        self.x11.XQueryTree(
            self.display, window, ctypes.byref(root), ctypes.byref(parent),
            ctypes.byref(children), ctypes.byref(count),
        )
        if children:
            self.x11.XFree(children)
        return parent.value

    def _top_level(self, window: int) -> int:
        root = self.x11.XDefaultRootWindow(self.display)
        current = window
        while True:
            parent = self._parent(current)
            if not parent or parent == root:
                return current
            current = parent

    def _name(self, window: int) -> str:
        name = ctypes.c_char_p()
        if self.x11.XFetchName(self.display, window, ctypes.byref(name)) and name.value:
            value = name.value.decode("utf-8", "replace")
            self.x11.XFree(name)
            return value
        return ""

    def _find_window(self, wanted: str) -> int:
        pending = self._children(self.x11.XDefaultRootWindow(self.display))
        matches: list[tuple[int, int]] = []
        while pending:
            window = pending.pop()
            if wanted in self._name(window).casefold():
                width, height = self._size(window)
                # Wine may expose a tiny titled helper/control window alongside
                # the actual game client, especially inside a virtual desktop.
                if width >= 320 and height >= 240:
                    matches.append((width * height, window))
            pending.extend(self._children(window))
        # Mutter's decorative frame has the same title as the Wine client.
        return min(matches)[1] if matches else 0

    def _size(self, window: int) -> tuple[int, int]:
        root = ctypes.c_ulong()
        x = ctypes.c_int()
        y = ctypes.c_int()
        width = ctypes.c_uint()
        height = ctypes.c_uint()
        border = ctypes.c_uint()
        depth = ctypes.c_uint()
        self.x11.XGetGeometry(
            self.display, window, ctypes.byref(root), ctypes.byref(x),
            ctypes.byref(y), ctypes.byref(width), ctypes.byref(height),
            ctypes.byref(border), ctypes.byref(depth),
        )
        return width.value, height.value

    def _root_point(self, x: int, y: int) -> tuple[int, int]:
        root = self.x11.XDefaultRootWindow(self.display)
        root_x = ctypes.c_int()
        root_y = ctypes.c_int()
        child = ctypes.c_ulong()
        self.x11.XTranslateCoordinates(
            self.display, self.window, root, x, y, ctypes.byref(root_x),
            ctypes.byref(root_y), ctypes.byref(child),
        )
        return root_x.value, root_y.value

    def focus(self) -> None:
        # Reparenting window managers may give the title to the outer frame, but
        # XSetInputFocus still delivers synthetic keys to its active child.
        self.x11.XMapRaised(self.display, self.frame)
        self.x11.XSetInputFocus(self.display, self.window, 1, 0)
        self.x11.XFlush(self.display)

    def key(self, name: str) -> None:
        keysym = self.x11.XStringToKeysym(name.encode("ascii"))
        keycode = self.x11.XKeysymToKeycode(self.display, keysym)
        if not keycode:
            raise RuntimeError(f"X11 has no keycode for {name!r}")
        self.xtst.XTestFakeKeyEvent(self.display, keycode, True, 0)
        self.xtst.XTestFakeKeyEvent(self.display, keycode, False, 0)

    def type_word(self, word: str, delay: float) -> None:
        self.focus()
        time.sleep(0.15)
        for letter in word.lower():
            self.key(letter)
            self.x11.XFlush(self.display)
            time.sleep(delay)
        self.key("Return")
        self.x11.XFlush(self.display)

    def click(self, x: int, y: int, delay: float) -> None:
        root_x, root_y = self._root_point(x, y)
        self.xtst.XTestFakeMotionEvent(self.display, -1, root_x, root_y, 0)
        self.xtst.XTestFakeButtonEvent(self.display, 1, True, 0)
        self.xtst.XTestFakeButtonEvent(self.display, 1, False, 0)
        self.x11.XFlush(self.display)
        time.sleep(delay)

    def clear_selection(self, delay: float) -> None:
        """Bookworm uses right-click anywhere in the board to deselect all."""
        width, height = self._size(self.window)
        root_x, root_y = self._root_point(width // 2, int(height * 0.70))
        self.xtst.XTestFakeMotionEvent(self.display, -1, root_x, root_y, 0)
        self.xtst.XTestFakeButtonEvent(self.display, 3, True, 0)
        self.xtst.XTestFakeButtonEvent(self.display, 3, False, 0)
        self.x11.XFlush(self.display)
        time.sleep(delay)

    def scramble(self, delay: float) -> None:
        """Click Deluxe's Scramble control on the bottom action strip."""
        if self.layout != "deluxe":
            raise RuntimeError("Automated Scramble is currently calibrated only for Deluxe")
        self.focus()
        time.sleep(0.2)
        width, height = self._size(self.window)
        self.click(int(width * 0.19), int(height * 0.963), delay)

    def dismiss_invalid_word_dialog(self, delay: float) -> None:
        """Dismiss Deluxe's centered invalid-word dialog, if it is present.

        The same click lands harmlessly in the arena when no dialog is open.
        """
        if self.layout != "deluxe":
            return
        self.focus()
        width, height = self._size(self.window)
        self.click(width // 2, int(height * 0.470), delay)

    def advance_dialog(self, kind: str, delay: float) -> None:
        """Click a Lua-confirmed Deluxe dialogue's primary continuation area."""
        if self.layout != "deluxe":
            raise RuntimeError("Automated dialogue is calibrated only for Deluxe")
        points = {
            "levelup": (0.50, 0.665),
            "conversation": (0.50, 0.60),
        }
        if kind not in points:
            raise RuntimeError(f"No click calibration for dialogue kind {kind!r}")
        width, height = self._size(self.window)
        x, y = points[kind]
        self.focus()
        self.click(int(width * x), int(height * y), delay)

    def open_battle_menu(self, delay: float) -> None:
        """Open Deluxe's in-battle menu from the bottom action strip."""
        if self.layout != "deluxe":
            raise RuntimeError("Battle-menu automation is calibrated only for Deluxe")
        width, height = self._size(self.window)
        self.focus()
        self.click(int(width * 0.875), int(height * 0.963), delay)

    def quit_to_main_menu(self, delay: float) -> None:
        """Click Quit To Main Menu on an already-open Deluxe battle menu."""
        if self.layout != "deluxe":
            raise RuntimeError("Main-menu automation is calibrated only for Deluxe")
        width, height = self._size(self.window)
        self.focus()
        self.click(int(width * 0.500), int(height * 0.530), delay)

    def confirm_quit_to_main_menu(self, delay: float) -> None:
        """Confirm Deluxe's saved-progress main-menu exit prompt."""
        if self.layout != "deluxe":
            raise RuntimeError("Main-menu automation is calibrated only for Deluxe")
        width, height = self._size(self.window)
        self.focus()
        self.click(int(width * 0.415), int(height * 0.650), delay)

    def start_adventure(self, delay: float) -> None:
        """Choose Adventure from Deluxe's main menu."""
        if self.layout != "deluxe":
            raise RuntimeError("Adventure automation is calibrated only for Deluxe")
        width, height = self._size(self.window)
        self.focus()
        # The Adventure hotspot is the upper half of the Greek building left
        # of Lex. Lower points can land on the path and do nothing at 800x600.
        self.click(int(width * 0.300), int(height * 0.480), delay)

    def enter_chapter(self, delay: float) -> None:
        """Click Enter on Deluxe's chapter map."""
        if self.layout != "deluxe":
            raise RuntimeError("Chapter-map automation is calibrated only for Deluxe")
        width, height = self._size(self.window)
        self.focus()
        self.click(int(width * 0.500), int(height * 0.963), delay)

    def confirm_skip_minigame(self, delay: float) -> None:
        """Choose Yes when chapter entry offers to skip a mini-game."""
        if self.layout != "deluxe":
            raise RuntimeError("Mini-game skip is calibrated only for Deluxe")
        width, height = self._size(self.window)
        self.focus()
        self.click(int(width * 0.415), int(height * 0.683), delay)

    def select_treasures(self, slots: tuple[int, ...], delay: float) -> None:
        """Select zero-based Deluxe treasure-grid slots and continue."""
        if self.layout != "deluxe":
            raise RuntimeError("Treasure selection is calibrated only for Deluxe")
        width, height = self._size(self.window)
        columns = (0.243, 0.330, 0.414, 0.499, 0.583, 0.668, 0.751)
        rows = (0.172, 0.342, 0.512, 0.682)
        self.focus()
        for slot in slots:
            column, row = divmod(slot, 4)
            if column >= len(columns):
                raise RuntimeError(f"Treasure slot {slot} is outside the calibrated grid")
            self.click(
                int(width * columns[column]), int(height * rows[row]), delay
            )
        self.click(int(width * 0.500), int(height * 0.963), delay)

    def change_user(self, delay: float) -> None:
        """Open Select a User from the Deluxe main-menu welcome panel."""
        if self.layout != "deluxe":
            raise RuntimeError("Profile automation is calibrated only for Deluxe")
        width, height = self._size(self.window)
        self.focus()
        self.click(int(width * 0.500), int(height * 0.340), delay)

    def delete_selected_user(self, delay: float) -> None:
        """Click Delete for the currently selected user."""
        width, height = self._size(self.window)
        self.focus()
        self.click(int(width * 0.605), int(height * 0.700), delay)

    def confirm_delete_user(self, delay: float) -> None:
        """Click Yes in the irreversible profile-deletion confirmation."""
        width, height = self._size(self.window)
        self.focus()
        self.click(int(width * 0.415), int(height * 0.670), delay)

    def create_new_user(self, delay: float) -> None:
        """Open the New User name dialog."""
        width, height = self._size(self.window)
        self.focus()
        self.click(int(width * 0.415), int(height * 0.700), delay)

    def replace_user_name(self, old_name: str, new_name: str, delay: float) -> None:
        """Replace the prefilled deleted name and submit the New User dialog."""
        self.focus()
        for _ in old_name:
            self.key("BackSpace")
            self.x11.XFlush(self.display)
            time.sleep(delay)
        for character in new_name.casefold():
            self.key(character)
            self.x11.XFlush(self.display)
            time.sleep(delay)
        self.key("Return")
        self.x11.XFlush(self.display)
        time.sleep(delay)

    def skip_intro(self, delay: float) -> None:
        """Click the explicit 'Click anywhere to skip' introduction screen."""
        width, height = self._size(self.window)
        self.focus()
        self.click(width // 2, int(height * 0.500), delay)

    def play_word(
        self,
        board_text: str,
        word: str,
        delay: float,
        settle: float,
        path: tuple[int, ...] | None = None,
    ) -> None:
        self.focus()
        time.sleep(0.2)
        self.clear_selection(delay)
        board = parse_board(board_text)
        positions: dict[str, list[tuple[int, int]]] = {}
        for row, values in enumerate(board.grid):
            for column, letter in enumerate(values):
                positions.setdefault(letter, []).append((row, column))

        width, height = self._size(self.window)
        # Centers measured as fractions of the PopCap 640x480 client. They
        # remain correct when desktop scaling gives Wine a 540x405 client.
        if self.layout == "deluxe":
            # Measured from the native Deluxe client inside Wine's 800x600
            # virtual desktop. Deluxe positions its rack higher and slightly
            # farther right than the source/web build.
            tile_x = (0.3815, 0.4610, 0.5430, 0.6220)
            tile_y = (0.5617, 0.6483, 0.7333, 0.8183)
        else:
            tile_x = (0.3815, 0.4610, 0.5430, 0.6220)
            tile_y = (0.5060, 0.6200, 0.7310, 0.8420)
        for offset, letter in enumerate(word.upper()):
            if path is not None:
                row, column = divmod(path[offset], 4)
                if board.grid[row][column] != letter:
                    raise RuntimeError(
                        f"Optimizer path points at {board.grid[row][column]}, expected {letter}"
                    )
            else:
                choices = positions.get(letter)
                if not choices:
                    raise RuntimeError(f"No unused {letter} tile for {word.upper()}")
                row, column = choices.pop(0)
            self.click(int(width * tile_x[column]), int(height * tile_y[row]), delay)
        time.sleep(settle)
        self.click(width // 2, int(height * 0.963), delay)


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
