from collections import Counter

from board.generate_board import Board
from calculate_damage.calculate_damage import Modifiers, calculate_damage
from word.word import Word


def setup(word_dict: dict[str, float]) -> dict[str, Counter]:
    return {word: Counter(word.upper()) for word in word_dict if len(word) <= 16}


def solve_board(
    board: Board,
    word_dict: dict[str, float],
    word_counters: dict[str, Counter],
    mod: Modifiers,
) -> tuple[str, float] | None:
    available = Counter(letter.upper() for row in board.grid for letter in row)
    no_mods = not mod.parrot and mod.hand is None and mod.arch is None
    best_word, best_damage = None, 0.0

    for word, base in word_dict.items():
        if word_counters.get(word, Counter(word.upper())) <= available:
            damage = base if no_mods else calculate_damage(Word(word), mod)
            if damage > best_damage:
                best_word, best_damage = word, damage

    return (best_word, best_damage) if best_word else None
