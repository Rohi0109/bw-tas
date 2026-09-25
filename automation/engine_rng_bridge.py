"""Build-specific bridge from Lua randomseed to the native engine RNG seeder.

Only for an isolated experiment. The Lua binding passes a cdecl stack argument;
the engine seed routine expects EAX. Adapt that one call, leaving CRT srand and
both generators' draw implementations intact.
"""

import hashlib
import struct

SOURCE_HASH = 'e7eafcba6b79eca4bb39de8e5a80f1d0eb259a76cfe37dbde6ef7d7642a29192'
BASE = 0x400000
CALL = 0x4ce285
ADAPTER = 0x5ab492
SEED = 0x5ab440


def bridge(data):
    if hashlib.sha256(data).hexdigest() != SOURCE_HASH:
        raise ValueError('Unrecognized executable for engine RNG bridge')
    call, adapter = CALL - BASE, ADAPTER - BASE
    if data[call:call+5] != bytes.fromhex('e8 04 87 19 00'):
        raise ValueError('Lua randomseed call signature mismatch')
    if data[adapter:adapter+14] != b'\xcc' * 14:
        raise ValueError('Expected unused executable alignment padding')
    result = bytearray(data)
    # mov eax,[esp+4]; jmp engine_seed. Tail call returns to the original
    # Lua binding; its add esp,4 still removes the seed argument.
    thunk = bytes.fromhex('8b 44 24 04 e9') + struct.pack('<i', SEED-(ADAPTER+9))
    result[adapter:adapter+len(thunk)] = thunk
    result[call:call+5] = b'\xe8' + struct.pack('<i', ADAPTER-(CALL+5))
    return bytes(result)
