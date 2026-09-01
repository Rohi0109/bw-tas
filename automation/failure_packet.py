#!/usr/bin/env python3
"""Build a small, repeatable incident packet for a stalled TAS run."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUTOMATION_MARKER = "AUTOMATION_"


def tail_lines(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    # lua.log is currently small enough to read directly. Keeping this helper
    # isolated makes it easy to replace with a reverse/block reader later.
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]


def relevant_lines(lines: list[str], limit: int) -> list[str]:
    marked = [line for line in lines if AUTOMATION_MARKER in line]
    return (marked or lines)[-limit:]


def git_output(repo: Path, *args: str, limit: int = 16_000) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, text=True, capture_output=True, timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git unavailable: {exc}"
    output = (result.stdout + result.stderr).strip()
    if len(output) > limit:
        return output[:limit] + "\n... [truncated]"
    return output


def stall_signature(reason: str, lines: list[str]) -> str:
    normalized = "\n".join(line.strip() for line in lines[-30:])
    return hashlib.sha256(f"{reason}\n{normalized}".encode()).hexdigest()[:16]


def build_packet(
    *, repo: Path, log: Path, reason: str, command: list[str],
    process_output: list[str] | None = None, log_line_limit: int = 200,
    screenshot: Path | None = None,
) -> dict[str, Any]:
    log_tail = relevant_lines(tail_lines(log, max(log_line_limit * 3, 300)), log_line_limit)
    output_tail = (process_output or [])[-100:]
    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "signature": stall_signature(reason, log_tail),
        "command": command,
        "log_path": str(log),
        "log_tail": log_tail,
        "process_output_tail": output_tail,
        "screenshot_path": str(screenshot) if screenshot is not None else None,
        "git_status": git_output(repo, "status", "--short", limit=8_000),
        "git_diff_stat": git_output(repo, "diff", "--stat", limit=8_000),
        "instructions": (
            "Diagnose this single TAS stall. Make the smallest targeted fix in the "
            "repository, preserve unrelated user changes, run focused tests, and report "
            "the cause, changed files, tests, and whether a retry is safe."
        ),
    }


def write_packet(packet: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    packet = build_packet(
        repo=args.repo.resolve(), log=args.log.resolve(), reason=args.reason,
        command=command,
    )
    write_packet(packet, args.output)
    print(f"Wrote {args.output} (signature {packet['signature']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
