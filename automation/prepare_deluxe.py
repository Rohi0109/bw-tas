#!/usr/bin/env python3
"""Create a safe Bookworm Adventures Deluxe copy with TAS Lua hooks."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "BookwormAdventuresModding"
DEFAULT_SOURCE = (
    ROOT
    / "runtime/wineprefix/drive_c/Program Files (x86)/Popcap"
    / "Bookworm Adventures Deluxe/Bookworm Adventures Deluxe"
)
DEFAULT_OUTPUT = ROOT / "runtime/deluxe-modded"

sys.path.insert(0, str(KIT))
from bwakit import popcap_pak, popcap_pak_repack  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_entry(pak: Path, archive_name: str, destination: Path) -> None:
    data, entries = popcap_pak.parse(str(pak))
    entry = next((item for item in entries if item["name"] == archive_name), None)
    if entry is None:
        raise RuntimeError(f"{archive_name} is missing from {pak}")
    start = entry["data_off"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data[start : start + entry["size"]])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build an instrumented, disposable Deluxe installation"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    source_pak = source / "main.pak"
    if not source_pak.is_file():
        raise SystemExit(f"Deluxe main.pak was not found at {source_pak}")
    if source == output:
        raise SystemExit("Refusing to modify the source Deluxe installation")

    if not output.exists():
        print(f"Copying Deluxe installation to {output}")
        shutil.copytree(source, output)
    output_pak = output / "main.pak"
    pristine = output / ".tas-original-main.pak"
    if not pristine.exists():
        shutil.copy2(source_pak, pristine)
    elif sha256(pristine) != sha256(source_pak):
        raise SystemExit(
            "The source PAK changed since this modded copy was created. "
            "Move runtime/deluxe-modded aside and prepare it again."
        )

    with tempfile.TemporaryDirectory(prefix="bwa-deluxe-tas-") as temp_name:
        temp = Path(temp_name)
        original_tile = temp / "original" / "scripts" / "TileEngine.luc"
        patched_tile = temp / "modified" / "scripts" / "TileEngine.luc"
        original_battle = temp / "original" / "scripts" / "BattleEngine.luc"
        patched_battle = temp / "modified" / "scripts" / "BattleEngine.luc"
        extract_entry(pristine, "scripts\\TileEngine.luc", original_tile)
        extract_entry(pristine, "scripts\\BattleEngine.luc", original_battle)
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "automation/build_lua_hook.py"),
                "--input",
                str(original_tile),
                "--output",
                str(patched_tile),
            ],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "automation/build_battle_hook.py"),
                "--input", str(original_battle),
                "--output", str(patched_battle),
            ],
            check=True,
        )
        new_pak = temp / "main.pak"
        files, substituted, resized = popcap_pak_repack.repack(
            str(pristine), str(temp / "modified"), str(new_pak)
        )
        if substituted != 2:
            raise RuntimeError(
                f"Expected exactly two replaced PAK files, got {substituted}"
            )
        new_pak.replace(output_pak)

    tas_data = output / ".tas-data"
    extract_entry(
        pristine,
        "scripts\\wordlists\\metals.luc",
        tas_data / "metals.luc",
    )

    print(
        f"Prepared {output_pak} ({files} files, {substituted} hook replacement, "
        f"{resized} resized)"
    )
    print(f"Original installation remains unchanged: {source}")


if __name__ == "__main__":
    main()
