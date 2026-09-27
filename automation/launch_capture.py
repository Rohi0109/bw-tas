"""Bounded Wine parent-launch capture harness.

Owns the GDB + Wine process tree for one isolated capture session. Refuses
duplicate controllers. Verifies build identity. Enforces a wall-clock timeout.
Writes a run manifest whether the capture succeeded or timed out.

Usage:
    python3 automation/launch_capture.py \\
        --game-dir  runtime/experiments/sim-capture-v1 \\
        --wine-prefix runtime/experiments/sim-capture-prefix \\
        --output-dir runtime/experiments/run-<timestamp> \\
        [--draws 700] [--timeout 300] [--display :0]

The normal installation (runtime/deluxe-modded) is never touched.
Never run with --game-dir pointing at the normal install.
"""
import argparse
import hashlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path

EXE_HASH = '7fa527a59ff1108b98b0d18b0625d280029c0fd6c5fb3f91bb2f168b95968c67'
PROC_ROOT = Path('/proc')


def _pids_mapping_exe(exe_path: Path) -> list[int]:
    """Return PIDs whose /proc/PID/maps includes the given absolute path (Linux)."""
    target = str(exe_path)
    result = []
    if not PROC_ROOT.exists():
        return result
    for entry in PROC_ROOT.iterdir():
        if not entry.name.isdigit():
            continue
        maps = entry / 'maps'
        try:
            if target in maps.read_text(errors='replace'):
                result.append(int(entry.name))
        except OSError:
            pass
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game-dir', type=Path, required=True,
                        help='Staged isolated game directory (NOT the normal install)')
    parser.add_argument('--wine-prefix', type=Path, required=True,
                        help='Isolated Wine prefix for this capture session')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='New unique directory for all run artifacts')
    parser.add_argument('--draws', type=int, default=700,
                        help='Engine RNG draw budget 1–10000 (default 700)')
    parser.add_argument('--timeout', type=int, default=300,
                        help='Wall-clock seconds before forced kill (default 300)')
    parser.add_argument('--display', default=os.environ.get('DISPLAY', ':0'),
                        help='X11 display string (default: $DISPLAY or :0)')
    args = parser.parse_args()

    if not 1 <= args.draws <= 10000:
        parser.error('--draws must be in 1..10000')
    if args.timeout < 30:
        parser.error('--timeout must be at least 30 seconds')
    if args.output_dir.exists():
        parser.error('--output-dir already exists; supply a unique new path')

    game = args.game_dir.resolve()
    exe = game / 'BookwormAdventures.exe'
    pak = game / 'main.pak'

    for path in (exe, pak):
        if not path.exists():
            parser.error(f'Required file not found: {path}')

    exe_hash = _sha256(exe)
    if exe_hash != EXE_HASH:
        parser.error(f'Unsupported EXE build (hash starts {exe_hash[:16]}); '
                     'expected the pinned Deluxe build')
    pak_hash = _sha256(pak)

    # Process guard: refuse to launch if a process already maps this EXE
    existing = _pids_mapping_exe(exe)
    if existing:
        parser.error(f'Process(es) {existing} already map this EXE; '
                     'cannot launch a duplicate controller')

    args.output_dir.mkdir(parents=True)
    capture_file = args.output_dir / 'rng-capture.jsonl'
    combined_log = args.output_dir / 'gdb-combined.log'
    manifest_file = args.output_dir / 'run-manifest.json'

    build_id = {
        'BookwormAdventures.exe': exe_hash,
        'main.pak': pak_hash,
        'game_dir': str(game),
        'wine_prefix': str(args.wine_prefix.resolve()),
    }

    gdb_script = Path(__file__).with_name('launch_capture_gdb.py')

    env = dict(os.environ,
               WINEPREFIX=str(args.wine_prefix.resolve()),
               WINEDEBUG='-all',   # suppress Wine noise; game Lua print still goes through
               DISPLAY=args.display,
               BWA_CAPTURE_DRAWS=str(args.draws),
               BWA_CAPTURE_OUTPUT=str(capture_file),
               BWA_CAPTURE_BUILD=json.dumps(build_id))

    # GDB as process parent: --args sets the inferior; -ex sources the capture script.
    # -ex commands run before the inferior starts, so new_objfile events work.
    cmd = [
        'gdb', '--nx', '--quiet', '--batch',
        '-ex', f'source {gdb_script}',
        '--args', 'wine', str(exe),
    ]

    start_utc = time.time()
    start_mono = time.monotonic()

    manifest: dict = {
        'schema': 'launch-capture-v1',
        'cmd': cmd,
        'build': build_id,
        'draws_requested': args.draws,
        'timeout_s': args.timeout,
        'display': args.display,
        'start_utc': start_utc,
    }

    proc = None
    exit_code = 1
    timed_out = False

    try:
        with combined_log.open('wb') as log_fh:
            proc = subprocess.Popen(cmd, env=env, stdout=log_fh, stderr=log_fh)
            manifest['pid'] = proc.pid
            try:
                proc.wait(timeout=args.timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                exit_code = -signal.SIGTERM
    except Exception as exc:
        manifest['launch_error'] = str(exc)
        exit_code = 1
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()

    elapsed = time.monotonic() - start_mono
    manifest['elapsed_s'] = round(elapsed, 2)
    manifest['exit_code'] = exit_code
    manifest['timed_out'] = timed_out

    # Parse capture output for summary
    draws_captured = 0
    capture_complete = False
    capture_error = None

    if capture_file.exists():
        try:
            with capture_file.open() as f:
                lines = [json.loads(line) for line in f if line.strip()]
            footer = lines[-1] if lines else {}
            draws_captured = footer.get('draws', 0)
            capture_complete = bool(footer.get('complete'))
            capture_error = footer.get('error')
        except Exception as exc:
            manifest['capture_parse_error'] = str(exc)

    manifest['draws_captured'] = draws_captured
    manifest['capture_complete'] = capture_complete
    if capture_error:
        manifest['capture_error'] = capture_error

    manifest_file.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))

    return 0 if capture_complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
