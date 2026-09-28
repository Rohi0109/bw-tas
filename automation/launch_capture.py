"""Bounded Wine parent-launch capture harness.

Owns the GDB + Wine process tree for one isolated capture session. Refuses
duplicate controllers. Verifies build identity and staged-install provenance.
Enforces a wall-clock timeout. Kills the whole process group on exit.
Writes a run manifest whether the capture succeeded or timed out.

Usage:
    python3 automation/launch_capture.py \\
        --game-dir  runtime/experiments/sim-capture-v1 \\
        --wine-prefix runtime/experiments/sim-capture-prefix \\
        --output-dir runtime/experiments/run-<timestamp> \\
        [--draws 700] [--timeout 300] [--display :0]

The normal installation (runtime/deluxe-modded) is never touched.
--game-dir must contain sim-capture-manifest.json (produced by prepare_sim_capture.py).
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
STAGED_MARKER = 'sim-capture-manifest.json'
DEFAULT_WINE_PREFIX = Path.home() / '.wine'
STAGED_PROVENANCE_VALUE = 'prepare_sim_capture'
_REPO_ROOT = Path(__file__).parent.parent
NORMAL_GAME_DIR = (_REPO_ROOT / 'runtime' / 'deluxe-modded').resolve()
NORMAL_WINE_PREFIX = (_REPO_ROOT / 'runtime' / 'wineprefix').resolve()
CLEANUP_GRACE_S = 2


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


def _is_pgid_alive(pgid: int) -> bool:
    """True if any process in the given group is still running."""
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # group exists, we lack permission to signal it
    except OSError:
        return False


def _killpg_safe(pgid: int, sig: int) -> None:
    """Kill a process group, ignoring errors (group may already be gone)."""
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _cleanup_process_group(proc, pgid: int) -> None:
    """Terminate the owned process group; SIGKILL-escalate if SIGTERM is insufficient.

    Two branches:
    - proc still running: SIGKILL immediately (unexpected state, abort hard).
    - proc already exited (normal GDB completion): SIGTERM → grace → SIGKILL if alive.
    """
    if proc is not None and proc.poll() is None:
        if pgid is not None:
            _killpg_safe(pgid, signal.SIGKILL)
        proc.kill()
        proc.wait()
    elif pgid is not None:
        _killpg_safe(pgid, signal.SIGTERM)
        time.sleep(CLEANUP_GRACE_S)
        if _is_pgid_alive(pgid):
            _killpg_safe(pgid, signal.SIGKILL)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game-dir', type=Path, required=True,
                        help='Staged isolated game directory (must contain sim-capture-manifest.json)')
    parser.add_argument('--wine-prefix', type=Path, required=True,
                        help='Isolated Wine prefix for this capture session')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='New unique directory for all run artifacts')
    parser.add_argument('--draws', type=int, default=700,
                        help='Engine RNG draw budget 1-10000 (default 700)')
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
    prefix = args.wine_prefix.resolve()
    exe = game / 'BookwormAdventures.exe'
    pak = game / 'main.pak'
    marker = game / STAGED_MARKER

    # --- Isolation checks ---
    # Require the staging marker so the normal install cannot be selected accidentally.
    if not marker.exists():
        parser.error(
            f'--game-dir does not contain {STAGED_MARKER}; '
            'run prepare_sim_capture.py first to create an isolated staged copy')

    # Validate staged provenance so only prepare_sim_capture.py installs are accepted.
    try:
        staged_manifest = json.loads(marker.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        parser.error(f'{STAGED_MARKER} is not valid JSON: {exc}')
    if staged_manifest.get('staged_by') != STAGED_PROVENANCE_VALUE:
        parser.error(
            f'{STAGED_MARKER} lacks staged_by={STAGED_PROVENANCE_VALUE!r}; '
            'only installs prepared by prepare_sim_capture.py are accepted')

    for path in (exe, pak):
        if not path.exists():
            parser.error(f'Required file not found: {path}')

    # Reject the normal project installation and Wine prefix.
    if game == NORMAL_GAME_DIR:
        parser.error(
            '--game-dir is the normal project installation (runtime/deluxe-modded); '
            'only the staged capture copy prepared by prepare_sim_capture.py is accepted')
    if prefix == NORMAL_WINE_PREFIX:
        parser.error(
            '--wine-prefix is the normal project Wine prefix (runtime/wineprefix); '
            'supply an isolated prefix for this capture session')

    # Refuse if game-dir and wine-prefix are the same path.
    if game == prefix:
        parser.error('--game-dir and --wine-prefix must be different directories')

    # Refuse if wine-prefix is the user's default Wine prefix.
    default_prefix = Path(os.environ.get('WINEPREFIX', str(DEFAULT_WINE_PREFIX))).resolve()
    if prefix == default_prefix:
        parser.error(
            '--wine-prefix must not be the default Wine prefix; '
            'supply an isolated prefix created for this capture session')

    exe_hash = _sha256(exe)
    if exe_hash != EXE_HASH:
        parser.error(f'Unsupported EXE build (hash starts {exe_hash[:16]}); '
                     'expected the pinned Deluxe build')
    pak_hash = _sha256(pak)

    # Refuse if a process already maps this EXE (duplicate controller guard).
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
        'wine_prefix': str(prefix),
    }

    gdb_script = Path(__file__).with_name('launch_capture_gdb.py')

    env = dict(os.environ,
               WINEPREFIX=str(prefix),
               WINEDEBUG='-all',
               DISPLAY=args.display,
               BWA_CAPTURE_DRAWS=str(args.draws),
               BWA_CAPTURE_OUTPUT=str(capture_file),
               BWA_CAPTURE_BUILD=json.dumps(build_id))

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
    pgid = None
    exit_code = 1
    timed_out = False

    try:
        with combined_log.open('wb') as log_fh:
            # start_new_session=True creates a new session and process group so
            # we can kill GDB and all Wine descendants together via killpg.
            proc = subprocess.Popen(cmd, env=env, stdout=log_fh, stderr=log_fh,
                                    start_new_session=True)
            pgid = proc.pid  # group leader PID == proc PID after setsid
            manifest['pid'] = proc.pid
            manifest['pgid'] = pgid
            try:
                proc.wait(timeout=args.timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                # Kill the whole process group (GDB + Wine + game).
                _killpg_safe(pgid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _killpg_safe(pgid, signal.SIGKILL)
                    proc.wait()
                exit_code = -signal.SIGTERM
    except Exception as exc:
        manifest['launch_error'] = str(exc)
        exit_code = 1
    finally:
        _cleanup_process_group(proc, pgid)

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
