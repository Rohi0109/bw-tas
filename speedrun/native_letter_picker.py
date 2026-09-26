"""Recovered weight/selection kernel, not the complete rack generator.

The caller must supply the native-eligible candidate list, counts, integer
GetExtraLetterFreq results, and caller flag. Board blacklist filtering and draw
scheduling are not inferred here. See NATIVE_PICKER.md for instruction evidence.
"""

from string import ascii_uppercase
from collections import Counter
import hashlib
import re
import struct


BASE_WEIGHTS = (9420, 2200, 2000, 4200, 12700, 2000, 2500, 2000, 7330,
                700, 700, 4000, 2300, 6000, 7330, 2300, 600, 6900, 5600,
                6000, 4400, 1600, 1500, 500, 2100, 500)
COUNT_LIMITS = (4, 3, 3, 4, 4, 3, 4, 3, 4, 2, 2, 4, 3, 4, 3, 4,
                2, 4, 4, 4, 4, 3, 3, 2, 3, 2)
EXE_SHA256 = '7fa527a59ff1108b98b0d18b0625d280029c0fd6c5fb3f91bb2f168b95968c67'


def load_exclusions(executable):
    """Read the 41 native exclusion strings from pinned static initializers."""
    data = executable.read_bytes()
    if hashlib.sha256(data).hexdigest() != EXE_SHA256:
        raise ValueError('Unrecognized executable for exclusion table')
    found = {}
    for match in re.finditer(rb'\x68(.{4})\xb9(.{4})', data[0x2af700:0x2b0200], re.DOTALL):
        source, target = (struct.unpack('<I', group)[0] for group in match.groups())
        if 0x725e90 <= target < 0x72630c and (target-0x725e90) % 28 == 0:
            start = source - 0x400000
            end = data.index(b'\0', start)
            word = data[start:end].decode('ascii')
            if not re.fullmatch('[A-Z]{3,4}', word) or target in found:
                raise ValueError('Invalid native exclusion initializer')
            found[target] = word
    if len(found) != 41:
        raise ValueError('Incomplete native exclusion table')
    return tuple(found[address] for address in sorted(found))


def candidate_allowed(letter, patterns, excluded, vowels, consonants, total):
    """Recovered 0x476d90 helper, using explicit native row/column patterns."""
    # Native mutates each pattern copy from left to right, checking after each
    # hole replacement. Existing complete rows are not checked here.
    for original in patterns:
        row = list(original)
        for index, value in enumerate(row):
            if value == '*':
                row[index] = letter
                if ''.join(row) in excluded:
                    return False
    if total >= 9:
        if vowels >= 9 and letter in 'AEIOUY':
            return False
        if consonants >= 9 and letter not in 'AEIOUY':
            return False
    return True


def eligible_letters(board, excluded):
    """4x4 native eligibility projection; '*' denotes an absent tile.

    The caller must establish which native tiles count as present and pass the
    build's exclusion table. This does not remove/compact/refill the board.
    """
    if not re.fullmatch(r'[A-Z*]{4}(?:/[A-Z*]{4}){3}', board):
        raise ValueError('Expected 4x4 uppercase board with * for absent tiles')
    excluded = frozenset(excluded)
    if any(not re.fullmatch('[A-Z]{3,4}', word) for word in excluded):
        raise ValueError('Invalid exclusion strings')
    letters = board.replace('/', '')
    counts = Counter(letters.replace('*', ''))
    vowels = sum(counts[c] for c in 'AEIOUY')
    total = sum(counts.values())
    patterns = board.split('/') + [letters[column::4] for column in range(4)]
    eligible = ''.join(letter for i, letter in enumerate(ascii_uppercase)
                       if counts[letter] < COUNT_LIMITS[i]
                       and candidate_allowed(letter, patterns, excluded,
                                             vowels, total-vowels, total))
    # Native empty-candidate fallback at 0x47751e.
    return eligible or 'A'


def adjusted_weights(eligible, counts, extras, *, restrict_duplicates=False):
    """Integer kernel at 0x4775fe–0x4776a4 for the pinned Deluxe build.

    extras have already undergone the native Lua-number-to-int conversion.
    Negative/overflowing weights are outside this supported kernel domain.
    """
    if (not isinstance(eligible, str) or not eligible
            or any(c not in ascii_uppercase for c in eligible)
            or ''.join(sorted(set(eligible))) != eligible):
        raise ValueError('eligible must be nonempty, unique, ascending A–Z')
    if (len(counts) != 26 or len(extras) != 26
            or any(type(n) is not int or not 0 <= n <= 16 for n in counts)
            or any(type(n) is not int for n in extras)
            or type(restrict_duplicates) is not bool):
        raise ValueError('Expected 26 counts and integer frequency adjustments')
    result = []
    for letter in eligible:
        i = ord(letter) - ord('A')
        weight = BASE_WEIGHTS[i] + extras[i]
        if not 0 <= weight <= 0x7fffffff:
            raise ValueError('Unsupported negative or overflowing native weight')
        limit, count = COUNT_LIMITS[i], counts[i]
        if restrict_duplicates and limit != 4 and count == 2:
            weight = 0
        elif limit == 3 and count == 2:
            weight -= weight // 3
        elif limit == 4 and count == 2:
            weight -= weight // 6
        elif limit == 4 and count == 3:
            weight -= weight // 4
        result.append(weight)
    if not 0 < sum(result) <= 0x7fffffff:
        raise ValueError('Unsupported zero or overflowing total weight')
    return tuple(result)


def select_letter(eligible, weights, draw):
    """Native 31-bit draw modulo total, then first strict cumulative boundary."""
    if (not eligible or len(eligible) != len(weights)
            or any(c not in ascii_uppercase for c in eligible)
            or any(type(w) is not int or w < 0 for w in weights)
            or not 0 < sum(weights) <= 0x7fffffff
            or type(draw) is not int or not 0 <= draw <= 0x7fffffff):
        raise ValueError('Invalid native weighted-choice inputs')
    cursor = draw % sum(weights)
    for letter, weight in zip(eligible, weights):
        if cursor < weight:
            return letter
        cursor -= weight
    raise AssertionError('Unreachable cumulative selection')


def pick_letter(board, rng, excluded, extras, *, restrict_duplicates=False):
    """One explicit picker invocation; no guessed draw scheduling or tile flags.

    Invalid inputs are rejected before consuming RNG. The returned record makes
    filtering, weights and the raw draw inspectable during differential replay.
    """
    eligible = eligible_letters(board, excluded)
    counts = Counter(board.replace('/', '').replace('*', ''))
    weights = adjusted_weights(eligible, [counts[c] for c in ascii_uppercase],
                               extras, restrict_duplicates=restrict_duplicates)
    draw = rng.next_rand()
    return dict(letter=select_letter(eligible, weights, draw), draw=draw,
                eligible=eligible, weights=weights)
