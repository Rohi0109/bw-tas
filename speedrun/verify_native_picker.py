"""Differentially check picker kernels against original x86 bytes in Unicorn.

Requires an optional Unicorn environment and the pinned local executable.
Does not launch the game, emulate the entire picker, or write to its files.
"""

import argparse
import hashlib
import json
import random
import struct
from pathlib import Path

from native_letter_picker import BASE_WEIGHTS, COUNT_LIMITS, adjusted_weights, select_letter

EXE_SHA256 = '7fa527a59ff1108b98b0d18b0625d280029c0fd6c5fb3f91bb2f168b95968c67'


def verify(executable):
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
    from unicorn.x86_const import (UC_X86_REG_ESP, UC_X86_REG_EAX,
                                  UC_X86_REG_EBX, UC_X86_REG_EDI,
                                  UC_X86_REG_EBP, UC_X86_REG_EIP)
    data = executable.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXE_SHA256:
        raise ValueError('Unrecognized executable; inspect addresses before verification')
    if struct.unpack_from('<26i', data, 0x2c2770) != BASE_WEIGHTS:
        raise AssertionError('Native weight table differs')
    if struct.unpack_from('<26i', data, 0x2c27d8) != COUNT_LIMITS:
        raise AssertionError('Native count table differs')
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x477000, 0x1000)
    cpu.mem_write(0x477000, data[0x77000:0x78000])
    cpu.mem_map(0x6c2000, 0x1000)
    cpu.mem_write(0x6c2000, data[0x2c2000:0x2c3000])
    stack, letters = 0x100000, 0x102000
    cpu.mem_map(stack, 0x3000)

    def put(address, value):
        cpu.mem_write(address, struct.pack('<I', value & 0xffffffff))

    weight_checks = 0
    for flag in (False, True):
        for index in range(26):
            for count in range(5):
                for extra in (-499, 0, 1, 2, 1000):
                    counts, extras = [0]*26, [0]*26
                    counts[index], extras[index] = count, extra
                    letter = chr(65 + index)
                    # A zero single-candidate total is rejected by public API;
                    # include an unaffected candidate to inspect zero weights.
                    eligible = ''.join(sorted(set(letter + ('E' if letter != 'E' else 'A'))))
                    expected = adjusted_weights(eligible, counts, extras,
                                                restrict_duplicates=flag)[eligible.index(letter)]
                    cpu.reg_write(UC_X86_REG_ESP, stack)
                    cpu.reg_write(UC_X86_REG_EAX, extra & 0xffffffff)
                    cpu.reg_write(UC_X86_REG_EDI, index)
                    cpu.reg_write(UC_X86_REG_EBX, 0)
                    cpu.reg_write(UC_X86_REG_EBP, 2)
                    put(stack + 0xdc + index*4, BASE_WEIGHTS[index])
                    put(stack + 0x74 + index*4, count)
                    put(stack + 0x214, int(flag))
                    cpu.emu_start(0x4775fe, 0x477580, count=100)
                    if cpu.reg_read(UC_X86_REG_EIP) != 0x477580:
                        raise AssertionError('Native kernel did not reach expected exit')
                    actual = struct.unpack('<I', cpu.mem_read(stack+0xdc+index*4, 4))[0]
                    if actual != expected:
                        raise AssertionError((letter, count, extra, flag, actual, expected))
                    weight_checks += 1

    rng = random.Random(17)  # Test case generation only, not game RNG.
    selection_checks = 0
    for _ in range(100):
        eligible = ''.join(sorted(rng.sample('ABCDEFGHIJKLMNOPQRSTUVWXYZ', rng.randint(1, 26))))
        weights = tuple(rng.randrange(0, 20000) for _ in eligible)
        if not sum(weights):
            continue
        boundaries, total = {0, 0x7fffffff}, 0
        for weight in weights:
            total += weight
            boundaries.update((max(0, total-1), total))
        for draw in sorted(boundaries):
            cpu.reg_write(UC_X86_REG_ESP, stack)
            cpu.reg_write(UC_X86_REG_EAX, draw)
            cpu.reg_write(UC_X86_REG_EBX, total)
            cpu.mem_write(letters, eligible.encode())
            put(stack + 0x20, letters)
            put(stack + 0x24, letters + len(eligible))
            for letter, weight in zip(eligible, weights):
                put(stack + 0xdc + (ord(letter)-65)*4, weight)
            cpu.emu_start(0x4776f7, 0x477749, count=1000)
            if cpu.reg_read(UC_X86_REG_EIP) != 0x477749:
                raise AssertionError('Native selection did not reach expected exit')
            actual = chr(cpu.reg_read(UC_X86_REG_EAX) & 255)
            expected = select_letter(eligible, weights, draw)
            if actual != expected:
                raise AssertionError((eligible, weights, draw, actual, expected))
            selection_checks += 1
    return dict(executable_sha256=digest, weight_checks=weight_checks,
                selection_checks=selection_checks, mismatches=0,
                scope='Integer weight adjustment and cumulative selection only; supplied eligible candidates/extras/counts/draws')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.executable), indent=2))
