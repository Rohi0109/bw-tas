"""GDB Python entry point. Invoked by capture_native_rng.py, not ordinary Python."""
import hashlib
import json
import os
import struct
import time

import gdb

START, RETURN, STATE, CURSOR = 0x5ab4b0, 0x5ab5b0, 0x767030, 0x7679f0
EXPECTED = '1b8a735d03ad4582c943b5c8a6eb059f737f73071488b83bc3e1a911fb9c660a'
limit = int(os.environ['BWA_CAPTURE_DRAWS'])
output = open(os.environ['BWA_CAPTURE_OUTPUT'], 'x')
inferior = gdb.selected_inferior()
pending = None
count = 0
failure = None


def emit(record):
    output.write(json.dumps(record, separators=(',', ':'))+'\n')
    output.flush()


def snapshot():
    words = struct.unpack('<624I', bytes(inferior.read_memory(STATE, 2496)))
    cursor = struct.unpack('<I', bytes(inferior.read_memory(CURSOR, 4)))[0]
    return dict(words=words, cursor=cursor)


class Entry(gdb.Breakpoint):
    def stop(self):
        global pending, failure
        try:
            if pending is not None:
                raise ValueError('Overlapping RNG calls; capture cannot order this execution')
            stack = int(gdb.parse_and_eval('$esp')) & 0xffffffff
            caller = struct.unpack('<I', bytes(inferior.read_memory(stack, 4)))[0]
            pending = dict(index=count+1, caller=caller,
                           thread=gdb.selected_thread().global_num,
                           monotonic_ns=time.monotonic_ns(), before=snapshot())
            return False
        except Exception as exc:
            failure = str(exc)
            return True


class Returned(gdb.Breakpoint):
    def stop(self):
        global pending, count, failure
        try:
            if pending is None or pending['thread'] != gdb.selected_thread().global_num:
                raise ValueError('Unpaired RNG return')
            pending.update(kind='draw', value=int(gdb.parse_and_eval('$eax')) & 0xffffffff,
                           after=snapshot())
            emit(pending)
            pending = None
            count += 1
            return count >= limit
        except Exception as exc:
            failure = str(exc)
            return True


breakpoints = []
try:
    code = bytes(inferior.read_memory(START, 257))
    if hashlib.sha256(code).hexdigest() != EXPECTED:
        raise ValueError('Loaded RNG instructions do not match pinned build')
    emit(dict(kind='header', schema_version=1, pid=inferior.pid,
              build=json.loads(os.environ['BWA_CAPTURE_BUILD']),
              limitations=['Debugger pauses alter timing; no native timing claims.',
                           'Engine RNG only; not QRand/CRT or a whole-game checkpoint.']))
    # Parent launch can stop at the first draw with a temporary hardware gate.
    for gate in gdb.breakpoints() or []:
        if gate.location == f'*{START:#x}':
            gate.delete()
    breakpoints = [Entry(f'*{START:#x}', internal=True), Returned(f'*{RETURN:#x}', internal=True)]
    if int(gdb.parse_and_eval('$pc')) == START:
        if breakpoints[0].stop():
            raise ValueError(failure)
    gdb.execute('continue')
    emit(dict(kind='end', complete=count == limit and failure is None,
              draws=count, error=failure, pending=pending is not None))
finally:
    for breakpoint in breakpoints:
        breakpoint.delete()
    output.close()
    try:
        gdb.execute('detach')
    except gdb.error:
        pass
