"""Exact engine NextRand stream; separate from CRT/Lua RNG.

Recovered from Deluxe VA 0x5ab440 and 0x5ab4b0; see NATIVE_RNG.md.
Snapshots contain the 624 unsigned state words and the next-word cursor.
"""

from operator import index
from typing import NamedTuple


UINT32_MASK = 0xFFFFFFFF
RAND_MAX = 0x7FFFFFFF
DEFAULT_SEED = 0x1105
STATE_SIZE = 624


class NativeRngState(NamedTuple):
    words: tuple[int, ...]
    cursor: int


class NativeRng:
    """MT19937 with the engine's zero-seed substitution and 31-bit mask.

    The default models the initializer at 0x5ab410, not a claim that gameplay
    starts at this seed or has consumed no draws. Seeds use EAX's low 32 bits.
    """

    def __init__(self, seed: int = DEFAULT_SEED):
        self.seed(seed)

    def seed(self, seed: int) -> None:
        seed = (index(seed) & UINT32_MASK) or DEFAULT_SEED
        words = [seed]
        for i in range(1, STATE_SIZE):
            previous = words[-1]
            words.append((1812433253 * (previous ^ (previous >> 30)) + i)
                         & UINT32_MASK)
        self._words = words
        self._cursor = STATE_SIZE

    def next_rand(self) -> int:
        """Consume one native draw, returning an integer in [0, 2**31)."""
        words = self._words
        if self._cursor == STATE_SIZE:
            # Deliberately in place: wrapped references use newly twisted words.
            for i in range(STATE_SIZE):
                mixed = ((words[i] & 0x80000000)
                         | (words[(i + 1) % STATE_SIZE] & RAND_MAX))
                words[i] = (words[(i + 397) % STATE_SIZE] ^ (mixed >> 1)
                            ^ (0x9908B0DF if mixed & 1 else 0))
            self._cursor = 0
        value = words[self._cursor]
        self._cursor += 1
        value ^= value >> 11
        value ^= (value << 7) & 0x9D2C5680
        value ^= (value << 15) & 0xEFC60000
        value ^= value >> 18
        return value & RAND_MAX

    def snapshot(self) -> NativeRngState:
        """Return an immutable, independent state suitable for exact replay."""
        return NativeRngState(tuple(self._words), self._cursor)

    def restore(self, state: NativeRngState) -> None:
        """Restore (words, cursor); reject malformed state without mutation.

        Cursor 0..624 covers initialized native states. Corrupt/out-of-bounds
        native cursors are intentionally unsupported. All-zero words are valid
        for importing memory, even though normal seeding cannot produce them.
        """
        words, cursor = state
        words = tuple(index(word) for word in words)
        cursor = index(cursor)
        if len(words) != STATE_SIZE:
            raise ValueError('RNG state requires exactly 624 words')
        if any(word < 0 or word > UINT32_MASK for word in words):
            raise ValueError('RNG state words must be unsigned 32-bit integers')
        if not 0 <= cursor <= STATE_SIZE:
            raise ValueError('RNG cursor must be in 0..624')
        self._words = list(words)
        self._cursor = cursor

    # Familiar spellings for callers porting native or random.Random code.
    rand = next_rand
    getstate = snapshot
    setstate = restore
