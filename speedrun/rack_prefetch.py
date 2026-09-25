"""One-rack dictionary prefilter; never caches enemy-dependent decisions."""

from collections import Counter

from combat_models import DeluxeState, WordSpec
from deluxe_route import is_chapter_boss_defeat


class RackPrefetch:
    def __init__(self):
        self.board = None
        self.words = None

    def prepare(self, board: str, words: list[WordSpec], origin: DeluxeState | None) -> bool:
        # Chapter-end racks can be replaced during chapter generation. Do not
        # spend work on them or retain a cache from the preceding encounter.
        if origin is None or is_chapter_boss_defeat(origin):
            self.board = self.words = None
            return False
        letters = board.replace('/', '')
        if len(letters) != 16 or any(not 'A' <= c <= 'Z' for c in letters):
            self.board = self.words = None
            return False
        if board == self.board:
            return False
        available = Counter(letters)
        mask = 0
        for letter in available:
            mask |= 1 << (ord(letter)-ord('A'))
        self.words = [word for word in words if not word.letter_mask & ~mask
                      and all(available.get(c, 0) >= n for c, n in word.requirements)]
        self.board = board
        return True

    def take(self, board: str) -> list[WordSpec] | None:
        result = self.words if self.board == board else None
        self.board = self.words = None
        return result
