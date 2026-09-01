#!/usr/bin/env python3
"""Run the TAS, repair confirmed stalls with Codex, and safely retry."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tas_watchdog import run_watchdog


HERE = Path(__file__).resolve().parent


def is_infrastructure_failure(result: dict[str, Any]) -> bool:
    text = " ".join(
        [str(result.get("cause", "")), *map(str, result.get("tests", []))]
    ).lower()
    markers = ("sandbox", "bwrap", "rtm_newaddr", "repository access")
    return any(marker in text for marker in markers) and not result.get("changed_files")


def refund_attempt(repo: Path, signature: str) -> None:
    attempts_path = repo / "runtime/incidents/attempts.json"
    if not attempts_path.exists():
        return
    attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
    used = int(attempts.get(signature, 0))
    if used <= 1:
        attempts.pop(signature, None)
    else:
        attempts[signature] = used - 1
    attempts_path.write_text(
        json.dumps(attempts, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_repair_result(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"cause", "changed_files", "tests", "retry_safe"}
    missing = required.difference(data)
    if missing:
        raise ValueError(f"repair result missing: {', '.join(sorted(missing))}")
    if not isinstance(data["retry_safe"], bool):
        raise ValueError("repair result retry_safe is not a boolean")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=HERE.parent)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--incidents", type=Path, default=Path("runtime/incidents"))
    parser.add_argument("--stall-seconds", type=float, default=20.0)
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    parser.add_argument(
        "--screenshot", action=argparse.BooleanOptionalAction, default=True,
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("provide a TAS command after --")

    repo = args.repo.resolve()
    log = args.log if args.log.is_absolute() else repo / args.log
    incidents = args.incidents if args.incidents.is_absolute() else repo / args.incidents
    cycle = 0

    while True:
        cycle += 1
        print(f"AUTO_REPAIR: starting TAS cycle {cycle}", flush=True)
        code, packet = run_watchdog(
            command=command, repo=repo, log=log.resolve(), incidents=incidents,
            stall_seconds=args.stall_seconds,
            timeout_seconds=args.timeout_seconds, poll_seconds=args.poll_seconds,
            capture_screenshots=args.screenshot,
        )
        if packet is None:
            if code == 0:
                print("AUTO_REPAIR: TAS exited successfully; campaign loop complete.")
            else:
                print(f"AUTO_REPAIR: TAS exited with status {code}; no stall packet to repair.")
            return code

        print(f"AUTO_REPAIR: launching Codex for {packet}", flush=True)
        repair = subprocess.run(
            [
                sys.executable, str(HERE / "repair_loop.py"), str(packet),
                "--repo", str(repo), "--max-attempts", str(args.max_attempts),
                "--execute",
            ],
            cwd=repo,
            check=False,
        )
        if repair.returncode != 0:
            print(f"AUTO_REPAIR: repair stopped with status {repair.returncode}.")
            return repair.returncode

        result_path = packet.with_suffix(".codex-result.json")
        try:
            result = read_repair_result(result_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"AUTO_REPAIR: invalid Codex result: {exc}")
            return 3

        print(f"AUTO_REPAIR: cause: {result['cause']}")
        if not result["retry_safe"]:
            if is_infrastructure_failure(result):
                signature = str(json.loads(packet.read_text())["signature"])
                refund_attempt(repo, signature)
                print("AUTO_REPAIR: infrastructure failure did not consume a repair attempt.")
            print("AUTO_REPAIR: Codex did not mark the patch retry-safe; stopping.")
            return 4
        print("AUTO_REPAIR: patch is retry-safe; restarting TAS.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
