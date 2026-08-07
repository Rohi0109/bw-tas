#!/usr/bin/env python3
"""Build a PopCap `main.pak` from a directory tree.

This is a scratch packer for cases where no original `main.pak` is available.
It writes the simple XOR'd archive format used by Bookworm Adventures.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

XOR = 0xF7
MAGIC = 0xBAC04AC0


def xor_bytes(data: bytes) -> bytes:
    return bytes(b ^ XOR for b in data)


def windows_filetime_placeholder() -> bytes:
    # The runtime should not care about timestamps; use zero.
    return b"\x00" * 8


def iter_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def build_pak(input_dir: Path, output_pak: Path) -> int:
    files = iter_files(input_dir)

    header = struct.pack("<II", MAGIC, 0)
    table = bytearray()
    payloads = bytearray()

    for path in files:
        rel = path.relative_to(input_dir).as_posix().replace("/", "\\")
        rel_bytes = rel.encode("latin-1")
        data = path.read_bytes()
        if len(rel_bytes) > 255:
            raise ValueError(f"path too long for pak entry: {rel}")

        table += bytes((0x00, len(rel_bytes)))
        table += rel_bytes
        table += struct.pack("<I", len(data))
        table += windows_filetime_placeholder()
        payloads += data

    table += b"\x80"
    blob = header + bytes(table) + bytes(payloads)
    output_pak.parent.mkdir(parents=True, exist_ok=True)
    output_pak.write_bytes(xor_bytes(blob))
    return len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_pak", type=Path)
    args = parser.parse_args()

    count = build_pak(args.input_dir, args.output_pak)
    print(f"{args.output_pak} ({count} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
