from dataclasses import dataclass

from word.constats import LETTER_WEIGHTS


@dataclass
class Word:
    word_name: str

    def __post_init__(self):
        self.word_name = self.word_name.strip()

    @property
    def letters_count(self) -> int:
        return len(self.word_name)

    @property
    def base_damage(self) -> float:
        sum: float = 0
        for letter in self.word_name:
            sum += LETTER_WEIGHTS[letter.upper()]
        return sum
