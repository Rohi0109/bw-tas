#!/usr/bin/env python3
"""Launch one bounded Codex repair for a watchdog incident."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_attempts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    data = load_json(path)
    return {str(key): int(value) for key, value in data.items()}


def save_attempts(path: Path, attempts: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(attempts, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def codex_command(
    repo: Path, result: Path, screenshot: Path | None = None,
) -> list[str]:
    command = [
        # This host cannot initialize Codex's bubblewrap workspace sandbox
        # (RTM_NEWADDR/loopback fails). Keep the repair bounded by its prompt,
        # incident packet, output schema, and attempt cap instead.
        "codex", "exec", "--ephemeral", "--sandbox", "danger-full-access",
        "--output-schema", str(HERE / "codex-result.schema.json"),
        "--output-last-message", str(result), "-C", str(repo), "-",
    ]
    if screenshot is not None:
        command[2:2] = ["--image", str(screenshot)]
    return command


def make_prompt(packet: dict[str, Any]) -> str:
    return (
        "Work on exactly one Bookworm Adventures TAS incident. The repository may "
        "contain unrelated user changes: preserve them. Do not start an open-ended "
        "campaign run. Use no more than 12,000 tokens and at most 12 shell/tool calls. "
        "Inspect only files directly implicated by the incident before expanding scope. "
        "Diagnose from this bounded packet, make the smallest fix, and run focused "
        "tests. If evidence is insufficient, stop with retry_safe=false instead of "
        "performing broad exploration. Return the required JSON result.\n\nINCIDENT:\n"
        + json.dumps(packet, indent=2)
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument("--repo", type=Path, default=HERE.parent)
    parser.add_argument("--attempts", type=Path, default=Path("runtime/incidents/attempts.json"))
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument(
        "--execute", action="store_true",
        help="actually invoke Codex; without this flag, print the planned command",
    )
    args = parser.parse_args()
    packet = load_json(args.packet.resolve())
    signature = str(packet.get("signature", ""))
    if not signature:
        parser.error("packet has no signature")
    if args.max_attempts < 1:
        parser.error("--max-attempts must be positive")

    repo = args.repo.resolve()
    attempts_path = args.attempts
    if not attempts_path.is_absolute():
        attempts_path = repo / attempts_path
    attempts = load_attempts(attempts_path)
    used = attempts.get(signature, 0)
    if used >= args.max_attempts:
        print(f"Refusing repair: signature {signature} already has {used} attempts")
        return 2

    result = args.packet.resolve().with_suffix(".codex-result.json")
    screenshot_value = packet.get("screenshot_path")
    screenshot = Path(screenshot_value) if screenshot_value else None
    if screenshot is not None and not screenshot.exists():
        screenshot = None
    command = codex_command(repo, result, screenshot)
    if not args.execute:
        print("DRY RUN (add --execute to launch):")
        print(" ".join(command))
        print(f"signature={signature} attempt={used + 1}/{args.max_attempts}")
        return 0

    attempts[signature] = used + 1
    save_attempts(attempts_path, attempts)
    completed = subprocess.run(command, input=make_prompt(packet), text=True, check=False)
    if completed.returncode == 0:
        print(f"Codex result: {result}")
    else:
        print(f"Codex exited with status {completed.returncode}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
