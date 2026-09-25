#!/usr/bin/env python3
"""Run a TAS command and stop it when lua.log stops changing."""

from __future__ import annotations

import argparse
import json
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
    capture_screenshots: bool = False,
    quiet: bool = False, status_path: Path | None = None,
) -> tuple[int, Path | None]:
    started = time.monotonic()
    last_change = started
    stamp = log_stamp(log)
    output: deque[str] = deque(maxlen=100)
    process = subprocess.Popen(
        command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=0, start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    reason: str | None = None
    pending = b""
    last_status_at = float("-inf")
    attacks = 0
    warnings = 0
    latest_state = None
    latest_chapter = None
    latest_warning = None

    def record_line(raw: bytes) -> None:
        nonlocal attacks, warnings, latest_state, latest_chapter, latest_warning
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not quiet:
            print(line, flush=True)
        output.append(line[-2000:])
        if " INFO Attack " in line:
            attacks += 1
        if " INFO State " in line:
            latest_state = line[-500:]
        if "Timer entered " in line or "Chapter map ready for Chapter " in line:
            latest_chapter = line[-500:]
        if " WARNING " in line or " ERROR " in line:
            warnings += 1
            latest_warning = line[-500:]

    def save_status(state: str, *, code=None, packet=None) -> None:
        if status_path is None:
            return
        status_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = dict(
            status=state, pid=process.pid, elapsed_seconds=round(time.monotonic()-started, 1),
            updated_at=datetime.now(timezone.utc).isoformat(),
            attacks_submitted=attacks, warning_count=warnings,
            latest_state=latest_state, latest_chapter=latest_chapter,
            latest_warning=latest_warning, exit_code=code,
            failure_packet=str(packet) if packet else None,
            screenshots_enabled=capture_screenshots,
            note="Runner exit is not proof of campaign completion. This monitor makes no model calls.",
        )
        temporary = status_path.with_suffix(status_path.suffix + f".{process.pid}.tmp")
        temporary.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        temporary.replace(status_path)

    try:
        save_status("running")
        while process.poll() is None:
            for key, _ in selector.select(timeout=poll_seconds):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    record_line(line)
                # A child that never emits a newline must not block timers or
                # grow this monitor's memory without bound.
                if len(pending) > 65536:
                    record_line(pending[:65536])
                    pending = pending[65536:]

            current = log_stamp(log)
            if current != stamp:
                stamp = current
                last_change = time.monotonic()

            now = time.monotonic()
            if now - last_status_at >= 5:
                save_status("running")
                last_status_at = now
            if timeout_seconds is not None and now - started >= timeout_seconds:
                reason = f"process timeout after {timeout_seconds:g} seconds"
                break
            if now - last_change >= stall_seconds:
                reason = f"lua log unchanged for {stall_seconds:g} seconds"
                break
    except BaseException:
        stop_process(process)
        save_status("monitor-interrupted", code=process.returncode)
        process.stdout.close()
        raise
    finally:
        selector.close()

    if reason is None:
        # Drain bytes written just before exit without blocking on descendants
        # that might still hold the inherited pipe open.
        os.set_blocking(process.stdout.fileno(), False)
        for _ in range(16):
            try:
                chunk = os.read(process.stdout.fileno(), 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                record_line(line)
            if len(pending) > 65536:
                record_line(pending[:65536])
                pending = pending[65536:]
        if pending:
            record_line(pending)
        if process.returncode == 0:
            process.stdout.close()
            save_status("runner-exited", code=0)
            if quiet:
                print("MONITOR: runner exited with code 0 (not proof of campaign completion).", flush=True)
            return 0, None
        reason = f"runner exited with code {process.returncode}"

    print(f"WATCHDOG_FAILURE: {reason}", file=sys.stderr, flush=True)
    code = process.returncode if process.returncode is not None else 124
    stop_process(process)
    if pending:
        record_line(pending)
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
    save_status("failed", code=code, packet=path)
    print(f"Failure packet: {path}", file=sys.stderr, flush=True)
    if screenshot is not None:
        print(f"Stall screenshot: {screenshot}", file=sys.stderr, flush=True)
    return code, path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--incidents", type=Path, default=Path("runtime/incidents"))
    parser.add_argument("--stall-seconds", type=float, default=20.0)
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    parser.add_argument(
        "--screenshot", action=argparse.BooleanOptionalAction, default=False,
        help="opt in to a failure screenshot (default: disabled)",
    )
    parser.add_argument("--quiet", action="store_true", help="print only the terminal outcome")
    parser.add_argument("--status", type=Path, help="write a small local status JSON every five seconds")
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
        quiet=args.quiet, status_path=args.status,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
