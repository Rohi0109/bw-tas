"""Execute native candidate helper with stubbed C++ string/vector operations."""

import argparse
import hashlib
import json
from pathlib import Path
import random
import struct

from native_letter_picker import EXE_SHA256, candidate_allowed, load_exclusions


def verify(executable):
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                                  UC_X86_REG_ESP, UC_X86_REG_EIP)
    data = executable.read_bytes()
    if hashlib.sha256(data).hexdigest() != EXE_SHA256:
        raise ValueError('Unknown executable')
    exclusions = load_exclusions(executable)
    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    for address, size in [(0, 0x1000), (0x476000, 0x2000), (0x721000, 0x1000),
                          (0x100000, 0x20000), (0x400000, 0x10000),
                          (0x666000, 0x1000)]:
        cpu.mem_map(address, size)
    cpu.mem_write(0x476000, data[0x76000:0x78000])
    stack, obj, vector, pattern_base, exclusion_base = 0x101000, 0x102000, 0x103000, 0x104000, 0x105000
    end = 0x100100

    def put(address, value):
        cpu.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def get(address):
        return struct.unpack('<I', cpu.mem_read(address, 4))[0]

    def string(address, text):
        cpu.mem_write(address, bytes(28))
        cpu.mem_write(address+4, text.encode()+b'\0')
        put(address+20, len(text))
        put(address+24, 15)

    def finish(value=0, cleanup=0):
        sp = cpu.reg_read(UC_X86_REG_ESP)
        cpu.reg_write(UC_X86_REG_EAX, value & 0xffffffff)
        cpu.reg_write(UC_X86_REG_EIP, get(sp))
        cpu.reg_write(UC_X86_REG_ESP, sp+4+cleanup)

    def hook(_cpu, address, _size, _user):
        if address == 0x4046c0:  # vector<string>::size
            base = cpu.reg_read(UC_X86_REG_ECX)
            finish((get(base+8)-get(base+4))//28)
        elif address == 0x401aa0:  # short-string assign(source, offset, length)
            sp = cpu.reg_read(UC_X86_REG_ESP)
            source = get(sp+4)
            if get(sp+8) != 0 or get(sp+12) != 0xffffffff:
                raise AssertionError('Unexpected string-copy operation')
            destination = cpu.reg_read(UC_X86_REG_ECX)
            cpu.mem_write(destination, bytes(cpu.mem_read(source, 28)))
            finish(destination, 12)
        elif address == 0x402110:  # byte comparison; native caller handles lengths
            size = cpu.reg_read(UC_X86_REG_EAX)
            left = bytes(cpu.mem_read(cpu.reg_read(UC_X86_REG_ECX), size))
            right = bytes(cpu.mem_read(cpu.reg_read(UC_X86_REG_EDX), size))
            finish((left > right)-(left < right))
        elif address == 0x6661dd:  # compiler stack-cookie check
            finish(cpu.reg_read(UC_X86_REG_EAX))
        elif address in (0x6667dd, 0x666441):
            raise AssertionError(f'Unexpected native assertion/allocation at {address:x}')

    cpu.hook_add(UC_HOOK_CODE, hook)
    cursor = exclusion_base
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        group = [word for word in exclusions if word[0] == letter]
        base = obj+0x38+(ord(letter)-65)*16
        put(base+4, cursor)
        for word in group:
            string(cursor, word)
            cursor += 28
        put(base+8, cursor)

    def native(letter, patterns, vowels, consonants, total):
        put(vector+4, pattern_base)
        put(vector+8, pattern_base+28*len(patterns))
        for i, row in enumerate(patterns):
            string(pattern_base+28*i, row)
        cpu.reg_write(UC_X86_REG_ESP, stack)
        cpu.reg_write(UC_X86_REG_ECX, vector)
        for i, value in enumerate((end, obj, ord(letter), vowels, consonants, total)):
            put(stack+i*4, value)
        cpu.emu_start(0x476d90, end, count=100000)
        if cpu.reg_read(UC_X86_REG_EIP) != end:
            raise AssertionError('Candidate helper did not return')
        return bool(cpu.reg_read(UC_X86_REG_EAX) & 255)

    rng = random.Random(22)
    cases = []
    # Include every excluded string with each possible hole, not just random
    # racks that almost never exercise this filter.
    for word in exclusions:
        for i in range(len(word)):
            cases.append((word[i], [word[:i]+'*'+word[i+1:]], 0, 0, 0))
    for _ in range(500):
        rows = [''.join(rng.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ*') for _ in range(4)) for _ in range(8)]
        vowels, consonants = rng.randrange(17), rng.randrange(17)
        cases.append((rng.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ'), rows, vowels, consonants,
                      vowels+consonants))
    for letter, patterns, vowels, consonants, total in cases:
        expected = candidate_allowed(letter, patterns, exclusions, vowels, consonants, total)
        actual = native(letter, patterns, vowels, consonants, total)
        if expected != actual:
            raise AssertionError((letter, patterns, vowels, consonants, actual, expected))
    return dict(executable_sha256=EXE_SHA256, eligibility_checks=len(cases), mismatches=0,
                exclusions=len(exclusions), scope='Native helper; C++ string/vector operations stubbed; board projection not emulated')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.executable), indent=2))
