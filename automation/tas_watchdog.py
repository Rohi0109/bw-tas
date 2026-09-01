#!/usr/bin/env python3
"""Run a TAS command and stop it when lua.log stops changing."""

from __future__ import annotations

import argparse
import os
import selectors
import signal
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from failure_packet import build_packet, write_packet


def log_stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


def stop_process(process: subprocess.Popen[str], grace: float = 3.0) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=grace)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def incident_path(directory: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return directory / f"stall-{stamp}.json"


def capture_screenshot(path: Path) -> Path | None:
    """Capture the focused game window without making stall handling fragile."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            ["gnome-screenshot", "--window", "--file", str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return path if completed.returncode == 0 and path.exists() else None


def run_watchdog(
    *, command: list[str], repo: Path, log: Path, incidents: Path,
    stall_seconds: float, timeout_seconds: float | None, poll_seconds: float,
    capture_screenshots: bool = True,
) -> tuple[int, Path | None]:
    started = time.monotonic()
    last_change = started
    stamp = log_stamp(log)
    output: deque[str] = deque(maxlen=100)
    process = subprocess.Popen(
        command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    reason: str | None = None

    try:
        while process.poll() is None:
            for key, _ in selector.select(timeout=poll_seconds):
                line = key.fileobj.readline()
                if line:
                    print(line, end="", flush=True)
                    output.append(line.rstrip("\n"))

            current = log_stamp(log)
            if current != stamp:
                stamp = current
                last_change = time.monotonic()

            now = time.monotonic()
            if timeout_seconds is not None and now - started >= timeout_seconds:
                reason = f"process timeout after {timeout_seconds:g} seconds"
                break
            if now - last_change >= stall_seconds:
                reason = f"lua log unchanged for {stall_seconds:g} seconds"
                break
    finally:
        selector.close()

    if reason is None:
        process.stdout.close()
        return process.returncode or 0, None

    print(f"WATCHDOG_STALL: {reason}", file=sys.stderr, flush=True)
    stop_process(process)
    path = incident_path(incidents)
    screenshot = (
        capture_screenshot(path.with_suffix(".png"))
        if capture_screenshots else None
    )
    process.stdout.close()
    packet = build_packet(
        repo=repo, log=log, reason=reason, command=command,
        process_output=list(output), screenshot=screenshot,
    )
    write_packet(packet, path)
    print(f"Failure packet: {path}", file=sys.stderr, flush=True)
    if screenshot is not None:
        print(f"Stall screenshot: {screenshot}", file=sys.stderr, flush=True)
    return 124, path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--incidents", type=Path, default=Path("runtime/incidents"))
    parser.add_argument("--stall-seconds", type=float, default=20.0)
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    parser.add_argument(
        "--screenshot", action=argparse.BooleanOptionalAction, default=True,
        help="capture the focused window when a stall is detected (default: enabled)",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("provide a command after --")
    if args.stall_seconds <= 0 or args.poll_seconds <= 0:
        parser.error("stall and poll durations must be positive")

    repo = args.repo.resolve()
    incidents = args.incidents
    if not incidents.is_absolute():
        incidents = repo / incidents
    code, _ = run_watchdog(
        command=command, repo=repo, log=args.log.resolve(), incidents=incidents,
        stall_seconds=args.stall_seconds, timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds, capture_screenshots=args.screenshot,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
