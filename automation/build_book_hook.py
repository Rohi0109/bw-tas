#!/usr/bin/env python3
"""Add an exact native Moxie mini-game prompt edge to Book bytecode."""

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
    hook = transform.compile_method(
        str(ROOT / "automation/lua_hook/BookMiniGamePrompt.lua"), str(args.luac)
    )
    transform.append_bound_method(chunk, "Book", "AutomationMiniGamePrompt", hook)

    # PromptToPlayMiniGame first rejects unavailable/previously-handled games.
    # PC 13 is the first instruction on the branch that invokes gCApp:Prompt,
    # so this hook is emitted only for a native, visible confirmation panel.
    prompt = chunk.protos[bound_method_proto(chunk, "PromptToPlayMiniGame")]
    transform.inject_self_call(
        prompt, "AutomationMiniGamePrompt", arg_regs=[],
        ret_reg=prompt.maxstack, at_pc=13,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    transform.save_chunk(chunk, args.output)
    print(f"Patched {args.input} -> {args.output}")


if __name__ == "__main__":
    main()
