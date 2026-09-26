"""Monitor TAS telemetry, obtain local diagnosis, and bound runner restarts."""
import argparse
import fcntl
import json
import math
from pathlib import Path
import time

from local_worker import run
from tas_watchdog import run_watchdog

ROOT = Path(__file__).resolve().parents[1]


def diagnose(packet, model):
    # Do not forward incident instructions or the complete campaign log.
    evidence = {key: packet.get(key) for key in ('reason', 'signature')}
    for key in ('log_tail', 'process_output_tail'):
        evidence[key] = [str(line)[-300:] for line in packet.get(key, [])[-8:]]
    task = ('Diagnose this TAS failure from the evidence. Give a brief likely cause, '
            'one debugging check, and uncertainty. Do not propose shell commands or '
            'claim a fix. Restart policy is controlled by the supervisor, not you.\n'
            + json.dumps(evidence))
    try:
        return run(task, [], model, 1500, 120, context_size=4096)
    except Exception as exc:
        return dict(status='failed', error=str(exc))


def restart_allowed(code, packet, restarts, limit):
    # Total wall-time expiration is a stop request, never a transient fault.
    reason = packet.get('reason', '')
    return (restarts < limit and code > 0
            and (reason.startswith('lua log unchanged for ')
                 or reason.startswith('telemetry state unchanged for ')
                 or reason.startswith('runner exited with code ')))


def supervise(*, command, repo, log, incidents, model, max_restarts,
              stall_seconds, timeout_seconds, cooldown_seconds, progress_seconds=90):
    incidents.mkdir(parents=True, exist_ok=True)
    # A fixed repo lock prevents duplicate local supervisors even when their
    # incident directories differ. Existing external controllers must be stopped.
    lock_path = repo / 'runtime/local-watchdog.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A local watchdog is already running for this repository')
        restarts = 0
        while True:
            code, path = run_watchdog(
                command=command, repo=repo, log=log, incidents=incidents,
                stall_seconds=stall_seconds, timeout_seconds=timeout_seconds,
                poll_seconds=.25, capture_screenshots=False, quiet=True,
                progress_seconds=progress_seconds,
                status_path=incidents / 'local-status.json')
            if path is None:
                return code
            packet = json.loads(path.read_text())
            retry = restart_allowed(code, packet, restarts, max_restarts)
            print(f'LOCAL_WATCHDOG: diagnosing {path}', flush=True)
            report = diagnose(packet, model)
            report['recovery'] = dict(restart_runner=retry, restarts_used=restarts,
                                      max_restarts=max_restarts,
                                      policy='bounded restart; model output is advisory')
            with path.with_suffix('.local-diagnosis.json').open('x') as output:
                json.dump(report, output, indent=2)
                output.write('\n')
            if not retry:
                print('LOCAL_WATCHDOG: stopping; see incident and local diagnosis.', flush=True)
                return code
            restarts += 1
            print(f'LOCAL_WATCHDOG: restarting runner {restarts}/{max_restarts} '
                  f'after {cooldown_seconds:g}s', flush=True)
            time.sleep(cooldown_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--log', type=Path, default=Path('runtime/deluxe-modded/lua.log'))
    parser.add_argument('--incidents', type=Path, default=Path('runtime/incidents'))
    parser.add_argument('--model', default='deepseek-r1:1.5b')
    parser.add_argument('--max-restarts', type=int, default=1)
    parser.add_argument('--stall-seconds', type=float, default=20)
    parser.add_argument('--progress-seconds', type=float, default=90)
    parser.add_argument('--timeout-seconds', type=float, default=None)
    parser.add_argument('--cooldown-seconds', type=float, default=5)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not 0 <= args.max_restarts <= 3:
        parser.error('max-restarts must be 0..3')
    for value in (args.stall_seconds, args.progress_seconds, args.cooldown_seconds, args.timeout_seconds):
        if value is not None and (not math.isfinite(value) or value <= 0):
            parser.error('durations must be finite and positive')
    repo = args.repo.resolve()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        command = [str(repo / 'run-deluxe-speedrun-auto.sh')]
    resolve = lambda p: p if p.is_absolute() else repo / p
    return supervise(command=command, repo=repo, log=resolve(args.log),
                     incidents=resolve(args.incidents), model=args.model,
                     max_restarts=args.max_restarts, stall_seconds=args.stall_seconds,
                     timeout_seconds=args.timeout_seconds, cooldown_seconds=args.cooldown_seconds,
                     progress_seconds=args.progress_seconds)


if __name__ == '__main__':
    raise SystemExit(main())
