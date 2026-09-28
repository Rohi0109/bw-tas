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
import fcntl
import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
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
sys.path.insert(0, str(_REPO_ROOT / 'speedrun'))
from verify_rng_capture import verify


def _prefix_pids(prefix):
    """Find processes using this isolated prefix, including detached Wine children."""
    found = []
    for entry in PROC_ROOT.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            env = (entry / 'environ').read_bytes().split(b'\0')
            if ('WINEPREFIX=' + str(prefix)).encode() in env:
                found.append(int(entry.name))
        except OSError:
            pass
    return found


def _cleanup_wine_prefix(prefix):
    """Stop detached Wine processes only in the exclusively owned isolated prefix."""
    env = dict(os.environ, WINEPREFIX=str(prefix))
    subprocess.run(['wineserver', '-k'], env=env, timeout=10, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    subprocess.run(['wineserver', '-w'], env=env, timeout=10, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


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
        proc.wait(timeout=5)
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
    parser.add_argument('--preflight-only', action='store_true',
                        help='Verify staging, dependencies and display without launching the game')
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()

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
    for key, actual in (('executable_sha256', exe_hash), ('capture_pak_sha256', pak_hash)):
        if staged_manifest.get(key) != actual:
            parser.error(f'{STAGED_MARKER}: {key} does not match staged file')
    if staged_manifest.get('hook_sha256') != _sha256(Path(__file__).with_name('lua_hook') / 'DumpSimulationState.lua'):
        parser.error('Staged scalar hook is stale; prepare a fresh capture copy')
    if not prefix.is_dir():
        parser.error('Isolated Wine prefix must already exist')
    if any(args.output_dir == p or p in args.output_dir.parents for p in
           (game, prefix, NORMAL_GAME_DIR, NORMAL_WINE_PREFIX)):
        parser.error('Output directory must be outside game installations and Wine prefixes')

    # Match all copies: two isolated installs can still compete for X11 input.
    existing = _pids_mapping_exe(Path('BookwormAdventures.exe'))
    existing += _prefix_pids(prefix)
    if existing:
        parser.error(f'Process(es) {existing} already map this EXE; '
                     'cannot launch a duplicate controller')

    if args.preflight_only:
        missing = [name for name in ('gdb', 'wine', 'wineserver', 'xdpyinfo') if not shutil.which(name)]
        if missing:
            parser.error(f'Missing capture tools: {missing}')
        try:
            subprocess.run(['xdpyinfo', '-display', args.display], check=True, timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except (subprocess.SubprocessError, OSError) as exc:
            parser.error(f'X11 display unavailable: {exc}')
        print(json.dumps({'status': 'ready_for_bounded_capture_attempt',
                          'game_dir': str(game), 'wine_prefix': str(prefix),
                          'build': {'BookwormAdventures.exe': exe_hash, 'main.pak': pak_hash},
                          'live_capture_verified': False, 'full_game_parity': False}, indent=2))
        return 0

    # Hold until main returns. Refuse racing launches against this prefix.
    prefix_lock = (prefix / '.bwa-capture.lock').open('a')
    try:
        fcntl.flock(prefix_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('Another capture launcher owns this prefix')

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

    gdb_script = Path(__file__).resolve().with_name('launch_capture_gdb.py')

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
                                    start_new_session=True, cwd=game)
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
                    proc.wait(timeout=5)
                exit_code = -signal.SIGTERM
    except Exception as exc:
        manifest['launch_error'] = str(exc)
        exit_code = 1
    finally:
        try:
            _cleanup_process_group(proc, pgid)
        except (subprocess.SubprocessError, OSError) as exc:
            manifest['cleanup_error'] = str(exc)
        if proc is not None:
            try:
                _cleanup_wine_prefix(prefix)
                remaining = _prefix_pids(prefix)
                if remaining:
                    manifest['cleanup_error'] = f'Prefix processes remain: {remaining}'
            except (subprocess.SubprocessError, OSError) as exc:
                manifest['cleanup_error'] = str(exc)

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
            report = verify(lines)
            manifest['rng_verification'] = report
            capture_complete = (report.get('status') == 'match'
                                and report.get('draws_checked') == args.draws
                                and lines[0].get('build') == build_id)
        except Exception as exc:
            capture_complete = False
            manifest['capture_parse_error'] = str(exc)

    manifest['draws_captured'] = draws_captured
    manifest['capture_complete'] = capture_complete
    if capture_error:
        manifest['capture_error'] = capture_error

    manifest_file.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))

    return 0 if capture_complete and not timed_out and exit_code == 0 and not manifest.get('cleanup_error') else 1


if __name__ == '__main__':
    raise SystemExit(main())
