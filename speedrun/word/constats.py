from enum import Enum

LETTER_WEIGHTS: dict[str, float] = {
    "A": 1,
    "D": 1,
    "E": 1,
    "G": 1,
    "I": 1,
    "L": 1,
    "N": 1,
    "O": 1,
    "R": 1,
    "S": 1,
    "T": 1,
    "U": 1,
    "B": 1.25,
    "C": 1.25,
    "F": 1.25,
    "H": 1.25,
    "M": 1.25,
    "P": 1.25,
    "V": 1.5,
    "W": 1.5,
    "Y": 1.5,
    "J": 1.75,
    "K": 1.75,
    "Q": 1.75,
    "X": 2,
    "Z": 2,
    "QU": 2.75,
}


class Arch(Enum):
    XYZ = {"X": 2.0, "Y": 1.5, "Z": 2.0}
    XYZZY = {"X": 3.0, "Y": 3.0, "Z": 3.0}


class Hand(Enum):
    HEP = 1.25
    HER = 1.5
