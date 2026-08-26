#!/usr/bin/env python3
"""Add treasure-screen telemetry to the staged TreasureScreen bytecode."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "BookwormAdventuresModding"
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(ROOT / "automation"))

from modkit import transform  # noqa: E402
from build_lua_hook import bound_method_proto  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--luac", type=Path, default=KIT / "luac")
    args = parser.parse_args()

    chunk = transform.load_chunk(args.input)
    method = transform.compile_method(
        str(ROOT / "automation/lua_hook/DumpTreasureScreen.lua"), str(args.luac)
    )
    transform.append_bound_method(
        chunk, "TreasureScreen", "AutomationDumpTreasureScreen", method
    )
    clear_method = transform.compile_method(
        str(ROOT / "automation/lua_hook/ClearTreasureScreen.lua"), str(args.luac)
    )
    transform.append_bound_method(
        chunk, "TreasureScreen", "AutomationClearTreasureScreen", clear_method
    )
    update = chunk.protos[bound_method_proto(chunk, "Update")]
    transform.inject_self_call(
        update, "AutomationDumpTreasureScreen", arg_regs=[],
        ret_reg=update.maxstack, at_pc=0,
    )
    destructor = chunk.protos[bound_method_proto(chunk, "Destructor")]
    transform.inject_self_call(
        destructor, "AutomationClearTreasureScreen", arg_regs=[],
        ret_reg=destructor.maxstack, at_pc=0,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    transform.save_chunk(chunk, args.output)
    print(f"Patched {args.input} -> {args.output}")


if __name__ == "__main__":
    main()
