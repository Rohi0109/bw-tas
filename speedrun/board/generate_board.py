import random
from dataclasses import dataclass

vowels = "AEIOU"
consonants = "BCDFGHJKLMNPQRSTVWXYZ"


@dataclass
class Board:
    grid: list[list[str]]  # 4x4

    def __str__(self) -> str:
        return "\n".join(" ".join(row) for row in self.grid)


def generate_board() -> Board:
    pool = [random.choice(vowels) for _ in range(6)] + [
        random.choice(consonants) for _ in range(10)
    ]
    random.shuffle(pool)
    grid = [pool[i * 4 : (i + 1) * 4] for i in range(4)]
    return Board(grid=grid)
