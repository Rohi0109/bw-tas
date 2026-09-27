"""GDB Python entry point for parent-launched Wine capture.

Source this as the first -ex in a parent GDB launch:
    gdb --nx --quiet --batch \\
        -ex 'source automation/launch_capture_gdb.py' \\
        --args wine /path/to/BookwormAdventures.exe

Handles the exec chain (wine → wine-preloader → game) by watching for
the game binary via new_objfile events, then places a one-shot hardware
gate at the first RNG draw entry. Full capture logic mirrors
capture_native_rng_gdb.py so the output is verifiable with verify_rng_capture.py.

Environment variables (same as capture_native_rng.py):
  BWA_CAPTURE_DRAWS   integer draw budget
  BWA_CAPTURE_OUTPUT  path to new output .jsonl
  BWA_CAPTURE_BUILD   JSON build-identity dict
"""
import hashlib
import json
import os
import struct
import time

import gdb

EXE_NAME = 'BookwormAdventures.exe'
START = 0x5ab4b0   # NextRand entry
RETURN = 0x5ab5b0  # NextRand return
STATE = 0x767030   # 624-word engine state
CURSOR = 0x7679f0  # next-word cursor
EXPECTED_CODE = '1b8a735d03ad4582c943b5c8a6eb059f737f73071488b83bc3e1a911fb9c660a'

_limit = int(os.environ['BWA_CAPTURE_DRAWS'])
_build = json.loads(os.environ['BWA_CAPTURE_BUILD'])
_output_path = os.environ['BWA_CAPTURE_OUTPUT']

_out = None
_pending = None
_count = 0
_failure = None
_bps = []
_gate_set = False  # ensure we only set the gate once


def _emit(record):
    _out.write(json.dumps(record, separators=(',', ':')) + '\n')
    _out.flush()


def _snapshot():
    inf = gdb.selected_inferior()
    words = list(struct.unpack('<624I', bytes(inf.read_memory(STATE, 2496))))
    cursor = struct.unpack('<I', bytes(inf.read_memory(CURSOR, 4)))[0]
    return {'words': words, 'cursor': cursor}


class _Gate(gdb.Breakpoint):
    """One-shot hardware gate: fires at the first engine RNG draw, then activates
    the full Entry/Returned capture machinery. Deletes itself on first hit."""

    def stop(self):
        global _out, _failure, _bps
        self.delete()
        try:
            inf = gdb.selected_inferior()
            code = bytes(inf.read_memory(START, 257))
            if hashlib.sha256(code).hexdigest() != EXPECTED_CODE:
                raise ValueError('RNG instructions do not match pinned build; wrong EXE?')
            _out = open(_output_path, 'x')
            _emit({'kind': 'header', 'schema_version': 1, 'pid': inf.pid, 'build': _build,
                   'limitations': [
                       'Debugger pauses alter timing; no native timing claims.',
                       'Engine RNG only; not QRand/CRT or a whole-game checkpoint.',
                   ]})
            entry_bp = _Entry(f'*{START:#x}', internal=True)
            return_bp = _Returned(f'*{RETURN:#x}', internal=True)
            _bps.extend([entry_bp, return_bp])
            # PC is already at NextRand entry; capture the entry state now
            # so the first return is paired.
            if entry_bp.stop():
                raise ValueError(_failure)
            return False
        except Exception as exc:
            _failure = str(exc)
            return True  # stop GDB so harness sees failure


class _Entry(gdb.Breakpoint):
    def stop(self):
        global _pending, _failure
        try:
            if _pending is not None:
                raise ValueError('Overlapping RNG calls; cannot order execution')
            inf = gdb.selected_inferior()
            stack = int(gdb.parse_and_eval('$esp')) & 0xffffffff
            caller = struct.unpack('<I', bytes(inf.read_memory(stack, 4)))[0]
            _pending = {
                'index': _count + 1,
                'caller': caller,
                'thread': gdb.selected_thread().global_num,
                'monotonic_ns': time.monotonic_ns(),
                'before': _snapshot(),
            }
            return False
        except Exception as exc:
            _failure = str(exc)
            return True


class _Returned(gdb.Breakpoint):
    def stop(self):
        global _pending, _count, _failure
        try:
            if _pending is None or _pending['thread'] != gdb.selected_thread().global_num:
                raise ValueError('Unpaired RNG return')
            value = int(gdb.parse_and_eval('$eax')) & 0xffffffff
            _pending.update({'kind': 'draw', 'value': value, 'after': _snapshot()})
            _emit(_pending)
            _pending = None
            _count += 1
            return _count >= _limit
        except Exception as exc:
            _failure = str(exc)
            return True


def _on_new_objfile(event):
    """Watch for the game binary load and set the hardware gate once."""
    global _gate_set
    if _gate_set:
        return
    try:
        objfile = getattr(event, 'new_objfile', None)
        if objfile is None:
            return
        filename = str(getattr(objfile, 'filename', '') or '')
        if EXE_NAME not in filename:
            return
        _gate_set = True
        _Gate(f'*{START:#x}', type=gdb.BP_HARDWARE_BREAKPOINT, internal=True)
    except Exception as exc:
        # Log but don't crash the event handler
        print(f'LAUNCH_CAPTURE: gate setup error: {exc}')


# ---------- GDB configuration ----------
gdb.execute('set pagination off')
gdb.execute('set follow-fork-mode child')
gdb.execute('set detach-on-fork off')
# Wine uses SIGSYS for its internal signal router and generates SIGSEGV during
# 32-bit startup; pass both through without stopping.
gdb.execute('handle SIGSYS nostop noprint pass')
gdb.execute('handle SIGSEGV nostop noprint pass')

gdb.events.new_objfile.connect(_on_new_objfile)

# Start Wine → wine-preloader → game
gdb.execute('run')

# ---------- Cleanup ----------
# GDB stopped: draw limit reached, error, or inferior exited.
try:
    if _out is not None:
        _emit({'kind': 'end',
               'complete': (_count == _limit and _failure is None and _pending is None),
               'draws': _count,
               'error': _failure,
               'pending': _pending is not None})
        _out.close()
    for bp in _bps:
        try:
            bp.delete()
        except Exception:
            pass
    try:
        gdb.execute('detach')
    except gdb.error:
        pass
except Exception as exc:
    print(f'LAUNCH_CAPTURE: cleanup error: {exc}')
