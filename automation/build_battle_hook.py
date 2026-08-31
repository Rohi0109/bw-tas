#!/usr/bin/env python3
"""Add dialogue telemetry to the staged BattleEngine bytecode."""

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
        str(ROOT / "automation/lua_hook/DumpDialogs.lua"), str(args.luac)
    )
    transform.append_bound_method(
        chunk, "BattleEngine", "AutomationDumpDialogs", method
    )
    prebattle = transform.compile_method(
        str(ROOT / "automation/lua_hook/DumpPreBattleDialogs.lua"), str(args.luac)
    )
    transform.append_bound_method(
        chunk, "BattleEngine", "AutomationDumpPreBattleDialogs", prebattle
    )
    convpanel_update = chunk.protos[
        bound_method_proto(chunk, "GenericConvPanelUpdateCallback")
    ]
    transform.inject_self_call(
        convpanel_update, "AutomationDumpPreBattleDialogs", arg_regs=[],
        ret_reg=convpanel_update.maxstack, at_pc=0,
    )
    attack_method = transform.compile_method(
        str(ROOT / "automation/lua_hook/DumpAttackSubmitted.lua"), str(args.luac)
    )
    transform.append_bound_method(
        chunk, "BattleEngine", "AutomationAttackSubmitted", attack_method
    )
    submit = chunk.protos[bound_method_proto(chunk, "SubmitTiles")]
    transform.inject_self_call(
        submit, "AutomationAttackSubmitted", arg_regs=[],
        ret_reg=submit.maxstack, at_pc=0,
    )
    # Native widget and battle-state paths use different entry points. Hook
    # both; the Lua method shares one global state/heartbeat guard, so a frame
    # that reaches both cannot create unsafe independent dialogue streams.
    for update_name in ("UpdateF", "Update"):
        update = chunk.protos[bound_method_proto(chunk, update_name)]
        transform.inject_self_call(
            update, "AutomationDumpDialogs", arg_regs=[],
            ret_reg=update.maxstack, at_pc=0,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    transform.save_chunk(chunk, args.output)
    print(f"Patched {args.input} -> {args.output}")


if __name__ == "__main__":
    main()
