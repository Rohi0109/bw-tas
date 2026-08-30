#!/usr/bin/env python3
"""Add chapter-map state and transition telemetry to BookManager bytecode."""

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
    dump = transform.compile_method(
        str(ROOT / "automation/lua_hook/DumpChapterMap.lua"), str(args.luac)
    )
    transform.append_bound_method(
        chunk, "BookManager", "AutomationDumpChapterMap", dump
    )
    update = chunk.protos[bound_method_proto(chunk, "Update")]
    transform.inject_self_call(
        update, "AutomationDumpChapterMap", arg_regs=[],
        ret_reg=update.maxstack, at_pc=0,
    )

    actions = (
        ("ContinueButtonPressed", "AutomationChapterContinue", "ChapterContinue.lua"),
        ("MiniGamePromptCallback", "AutomationChapterMiniGame", "ChapterMiniGame.lua"),
        ("DoChapterTransition", "AutomationChapterTransition", "ChapterTransition.lua"),
        ("StartGame", "AutomationChapterStartGame", "ChapterStartGame.lua"),
    )
    for method_name, hook_name, source_name in actions:
        action = transform.compile_method(
            str(ROOT / "automation/lua_hook" / source_name), str(args.luac)
        )
        transform.append_bound_method(chunk, "BookManager", hook_name, action)
        method = chunk.protos[bound_method_proto(chunk, method_name)]
        transform.inject_self_call(
            method, hook_name, arg_regs=[],
            ret_reg=method.maxstack, at_pc=0,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    transform.save_chunk(chunk, args.output)
    print(f"Patched {args.input} -> {args.output}")


if __name__ == "__main__":
    main()
