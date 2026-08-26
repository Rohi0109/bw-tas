from word.word import Word
from word.constats import LETTER_WEIGHTS, Hand, Arch
from calculate_damage.set_modifiers import Modifiers





def add_parrot_damage(word:Word) -> float:
    if "R" in word.word_name.upper():
        return word.base_damage * 2
    return word.base_damage


def add_hand_damage(word: Word, option: Hand) -> float:
    return word.base_damage * option.value


def add_arch_damage(word: Word, version: Arch) -> float:
    # subtract arch overrides from base letter weights
    sum: float = 0
    for letter in word.word_name:
        sum += LETTER_WEIGHTS[letter.upper()] - version.value.get(letter.upper(), 0)
    return sum

def calculate_damage(word: Word, mod: Modifiers) -> float:
    total = word.base_damage
    if mod.parrot:
        total += add_parrot_damage(word)
    if mod.hand is not None:
        total += add_hand_damage(word, mod.hand)
    if mod.arch is not None:
        total += add_arch_damage(word, mod.arch)
    return total
