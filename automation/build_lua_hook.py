#!/usr/bin/env python3
"""Add an exact board-snapshot logger to the staged TileEngine bytecode."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "BookwormAdventuresModding"
sys.path.insert(0, str(KIT))

from modkit import transform as transform  # noqa: E402


def bound_method_proto(chunk, method_name: str) -> int:
    """Resolve CLASS.method = closure(proto) from the top-level bytecode."""
    wanted = method_name.encode()
    matches = []
    for pc, instruction in enumerate(chunk.code[:-1]):
        if (instruction & 0x3F) != transform.OP_CLOSURE:
            continue
        proto_index = (instruction >> 6) & 0x3FFFF
        following = chunk.code[pc + 1]
        if (following & 0x3F) not in (9, 38, 39, 40):
            continue
        key_field = (following >> 15) & 0x1FF
        if key_field < 250:
            continue
        kind, value = chunk.consts[key_field - 250]
        if kind == "str" and value.rstrip(b"\0") == wanted:
            matches.append(proto_index)
    if len(matches) != 1:
        raise RuntimeError(f"Expected one binding for {method_name}, got {matches}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "runtime/stage/scripts/TileEngine.luc",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "runtime/stage/scripts/TileEngine.luc",
    )
    parser.add_argument(
        "--luac", type=Path, default=KIT / "luac"
    )
    args = parser.parse_args()

    source = ROOT / "automation/lua_hook/DumpBoard.lua"
    original = args.input.resolve()
    output = args.output.resolve()
    backup = output.with_suffix(".luc.original")

    if output == original and not backup.exists():
        shutil.copy2(original, backup)

    # Always rebuild from the pristine backup when patching the live stage, so
    # rerunning this command never appends the method twice.
    base = backup if output == original and backup.exists() else original
    chunk = transform.load_chunk(base)
    method = transform.compile_method(str(source), str(args.luac))
    transform.append_bound_method(
        chunk, "TileEngine", "AutomationDumpBoard", method
    )

    # TileEngine:Setup is the active board-construction path. StartRound is not
    # called for the initial web-demo battle, despite its suggestive name.
    setup = bound_method_proto(chunk, "Setup")
    proto = chunk.protos[setup]
    return_pc = max(
        pc for pc, instruction in enumerate(proto.code)
        if (instruction & 0x3F) == transform.OP_RETURN
    )
    transform.inject_self_call(
        proto,
        "AutomationDumpBoard",
        arg_regs=[],
        ret_reg=proto.maxstack,
        at_pc=return_pc,
    )

    # Initial tile letters are assigned after Setup returns. Update runs once
    # per frame; AutomationDumpBoard itself suppresses unchanged snapshots.
    update_proto = chunk.protos[bound_method_proto(chunk, "Update")]
    transform.inject_self_call(
        update_proto,
        "AutomationDumpBoard",
        arg_regs=[],
        ret_reg=update_proto.maxstack,
        at_pc=0,
    )

    tile_stopped = bound_method_proto(chunk, "TileStoppedMoving")
    stopped_proto = chunk.protos[tile_stopped]
    transform.inject_self_call(
        stopped_proto,
        "AutomationDumpBoard",
        arg_regs=[],
        ret_reg=stopped_proto.maxstack,
        at_pc=0,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    transform.save_chunk(chunk, output)
    print(f"Patched {base} -> {output}")
    print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
