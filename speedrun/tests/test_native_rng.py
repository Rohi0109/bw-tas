"""Portable regression tests plus optional actual-EXE Unicorn oracle.

Run from the repository root with unittest discovery. Native checks require
Unicorn and the installed EXE (or BWA_NATIVE_RNG_EXE); neither is installed here.
"""

import hashlib
import os
from pathlib import Path
import struct
import unittest

from native_rng import DEFAULT_SEED, NativeRng, NativeRngState

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP
except ImportError:
    Uc = None


EXE = Path(os.environ.get('BWA_NATIVE_RNG_EXE', str(
    Path(__file__).resolve().parents[2]
    / 'runtime/deluxe-modded/BookwormAdventures.exe')))


class NativeRngTests(unittest.TestCase):
    def test_standard_mt_vector_with_native_mask(self):
        # Published MT19937 seed 5489 reference, masked (not right-shifted).
        expected = [3499211612, 581869302, 3890346734, 3586334585,
                    545404204, 4161255391, 3922919429, 949333985,
                    2715962298, 1323567403]
        rng = NativeRng(5489)
        self.assertEqual([rng.next_rand() for _ in expected],
                         [x & 0x7FFFFFFF for x in expected])

    def test_zero_default_and_seed_wrapping(self):
        for seed, equivalent in [(0, DEFAULT_SEED), (1 << 32, DEFAULT_SEED),
                                 (-1, 0xFFFFFFFF), ((1 << 32) + 1, 1)]:
            self.assertEqual(NativeRng(seed).snapshot(),
                             NativeRng(equivalent).snapshot())
        self.assertEqual(NativeRng().snapshot(), NativeRng(0).snapshot())
        self.assertEqual(NativeRng(1).snapshot().cursor, 624)
        self.assertEqual(NativeRng(1).snapshot().words[:3],
                         (1, 1812433254, 3713160357))
        with self.assertRaises(TypeError):
            NativeRng(1.5)

    def test_snapshot_replay_and_reseed(self):
        rng = NativeRng(17)
        for count in (0, 1, 226, 227, 623, 624, 625, 1249):
            rng.seed(17)
            for _ in range(count):
                rng.next_rand()
            saved = rng.snapshot()
            branch = NativeRng()
            branch.restore(saved)
            expected = [rng.next_rand() for _ in range(1300)]
            self.assertEqual([branch.next_rand() for _ in expected], expected)
            rng.restore(saved)
            self.assertEqual(rng.snapshot(), saved)
            self.assertEqual([rng.next_rand() for _ in expected], expected)
        rng.seed(17)
        self.assertEqual(rng.snapshot(), NativeRng(17).snapshot())

    def test_restore_validation_and_no_aliasing(self):
        rng = NativeRng(1)
        saved = rng.snapshot()
        for words, cursor in [(saved.words[:-1], 0), (saved.words, -1),
                              (saved.words, 625), ((-1,) * 624, 0),
                              ((1 << 32,) * 624, 0)]:
            with self.assertRaises(ValueError):
                rng.restore((words, cursor))
            self.assertEqual(rng.snapshot(), saved)
        words = list(saved.words)
        rng.restore((words, 0))
        words[0] = 999
        self.assertEqual(rng.snapshot().words, saved.words)
        rng.restore(((0,) * 624, 624))
        self.assertEqual(rng.next_rand(), 0)


class ExeOracle:
    """Map just recovered code/data; no PE entry point, OS, or game execution."""

    def __init__(self):
        data = EXE.read_bytes()
        pe = struct.unpack_from('<I', data, 0x3C)[0]
        sections = struct.unpack_from('<H', data, pe + 6)[0]
        optional_size = struct.unpack_from('<H', data, pe + 20)[0]
        base = struct.unpack_from('<I', data, pe + 24 + 28)[0]

        def read(va, size):
            for i in range(sections):
                offset = pe + 24 + optional_size + 40 * i
                _, rva, raw_size, raw = struct.unpack_from('<IIII', data, offset + 8)
                if rva <= va - base and va - base + size <= rva + raw_size:
                    start = raw + va - base - rva
                    return data[start:start + size]
            raise ValueError(f'Unmapped file VA {va:#x}')

        # Fail rather than silently verifying an unknown generator revision.
        for va, size, digest in [
            (0x5AB440, 82, '96f47b010daec267dd7d3cfbaa5f1fe9a9345a280dc997790c6b3c61e09cd68c'),
            (0x5AB4B0, 257, '1b8a735d03ad4582c943b5c8a6eb059f737f73071488b83bc3e1a911fb9c660a'),
        ]:
            if hashlib.sha256(read(va, size)).hexdigest() != digest:
                raise ValueError(f'Unexpected RNG bytes at {va:#x}')
        if read(0x72F914, 8) != bytes.fromhex('00000000dfb00899'):
            raise ValueError('Unexpected twist lookup table')
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for address in (0x5AB000, 0x72F000, 0x767000, 0x100000, 0x200000):
            self.uc.mem_map(address, 0x1000)
        self.uc.mem_write(0x5AB410, read(0x5AB410, 0x1A1))
        self.uc.mem_write(0x72F914, read(0x72F914, 8))

    def call(self, address, eax=0):
        self.uc.reg_write(UC_X86_REG_ESP, 0x100FF0)
        self.uc.mem_write(0x100FF0, struct.pack('<I', 0x200000))
        self.uc.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
        self.uc.emu_start(address, 0x200000, count=100000)
        if self.uc.reg_read(UC_X86_REG_ESP) != 0x100FF4:
            raise AssertionError('Native routine did not return')
        return self.uc.reg_read(UC_X86_REG_EAX)

    def snapshot(self):
        raw = self.uc.mem_read(0x767030, 625 * 4)
        values = struct.unpack('<625I', raw)
        return NativeRngState(values[:624], values[624])

    def restore(self, state):
        self.uc.mem_write(0x767030, struct.pack('<625I', *state.words, state.cursor))


@unittest.skipUnless(Uc is not None and EXE.is_file(), 'requires Unicorn and installed EXE')
class NativeExecutableTests(unittest.TestCase):
    def test_initializer(self):
        oracle = ExeOracle()
        self.assertEqual(oracle.call(0x5AB410), 0x767030)
        self.assertEqual(oracle.snapshot(), NativeRng().snapshot())

    def test_seeds_outputs_and_complete_state(self):
        oracle = ExeOracle()
        for seed in (0, 1, 4357, 5489, 0x7FFFFFFF, 0x80000000,
                     0xFFFFFFFF, -1, 1 << 32, (1 << 32) + 1):
            with self.subTest(seed=seed):
                oracle.call(0x5AB440, seed)
                rng = NativeRng(seed)
                self.assertEqual(oracle.snapshot(), rng.snapshot())
                for draw in range(2500):
                    self.assertEqual(oracle.call(0x5AB4B0), rng.next_rand(),
                                     (seed, draw))
                    if draw in (0, 225, 226, 227, 622, 623, 624, 1247, 1248, 2499):
                        self.assertEqual(oracle.snapshot(), rng.snapshot())

    def test_arbitrary_state_and_bidirectional_restore(self):
        oracle = ExeOracle()
        for cursor in (0, 1, 226, 227, 623, 624):
            words = tuple((i * 0x9E3779B9 + 0xDEADBEEF) & 0xFFFFFFFF
                          for i in range(624))
            rng = NativeRng()
            rng.restore((words, cursor))
            oracle.restore(rng.snapshot())
            for _ in range(700):
                self.assertEqual(oracle.call(0x5AB4A0), rng.next_rand())
            self.assertEqual(oracle.snapshot(), rng.snapshot())
            saved = oracle.snapshot()
            expected = [oracle.call(0x5AB4B0) for _ in range(700)]
            rng.restore(saved)
            self.assertEqual([rng.next_rand() for _ in expected], expected)
            oracle.restore(saved)
            self.assertEqual([oracle.call(0x5AB4B0) for _ in expected], expected)


if __name__ == '__main__':
    unittest.main()
