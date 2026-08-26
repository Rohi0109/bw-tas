#!/usr/bin/env python3
"""Extract simple Microsoft CAB archives used by this repo.

Supports:
- No compression
- MSZIP (typeCompress low nibble == 0x1)

This is enough for the Bookworm Adventures web/plugin payload cabinets.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CabFile:
    name: str
    size: int
    folder_index: int
    offset: int


@dataclass
class CabFolder:
    data_offset: int
    block_count: int
    compression_type: int


def read_cab(path: Path) -> tuple[list[CabFolder], list[CabFile], bytes, int]:
    data = path.read_bytes()
    if data[:4] != b"MSCF":
        raise ValueError(f"{path} is not a CAB file")

    file_table_offset = struct.unpack_from("<I", data, 16)[0]
    folder_count, file_count = struct.unpack_from("<HH", data, 26)
    flags = struct.unpack_from("<H", data, 30)[0]

    offset = 36
    if flags & 0x0004:
        _header_reserve, folder_reserve, data_reserve = struct.unpack_from("<HBB", data, offset)
        offset += 4
    else:
        folder_reserve = 0
        data_reserve = 0

    folders: list[CabFolder] = []
    for _ in range(folder_count):
        data_offset, block_count, compression_type = struct.unpack_from("<IHH", data, offset)
        offset += 8 + folder_reserve
        folders.append(CabFolder(data_offset, block_count, compression_type))

    files: list[CabFile] = []
    offset = file_table_offset
    for _ in range(file_count):
        size, folder_offset, folder_index, _date, _time, _attrs = struct.unpack_from(
            "<IIHHHH", data, offset
        )
        offset += 16
        name_end = data.index(0, offset)
        name = data[offset:name_end].decode("latin1", "replace")
        offset = name_end + 1
        files.append(CabFile(name, size, folder_index, folder_offset))

    return folders, files, data, data_reserve


def decompress_folder(data: bytes, folder: CabFolder, data_reserve: int) -> bytes:
    algorithm = folder.compression_type & 0x000F
    pos = folder.data_offset
    output = bytearray()

    for _ in range(folder.block_count):
        _checksum, compressed_size, uncompressed_size = struct.unpack_from("<IHH", data, pos)
        pos += 8 + data_reserve
        compressed = data[pos : pos + compressed_size]
        pos += compressed_size

        if algorithm == 0:
            chunk = compressed
        elif algorithm == 1:
            if compressed[:2] != b"CK":
                raise ValueError("Invalid MSZIP block header")
            history = bytes(output[-32768:]) if output else b""
            inflater = zlib.decompressobj(wbits=-15, zdict=history)
            chunk = inflater.decompress(compressed[2:]) + inflater.flush()
        else:
            raise ValueError(f"Unsupported CAB compression algorithm: {algorithm}")

        if len(chunk) != uncompressed_size:
            raise ValueError(
                f"Decompressed block size mismatch: expected {uncompressed_size}, got {len(chunk)}"
            )
        output.extend(chunk)

    return bytes(output)


def extract(cab_path: Path, output_dir: Path) -> None:
    folders, files, data, data_reserve = read_cab(cab_path)
    folder_bytes = [decompress_folder(data, folder, data_reserve) for folder in folders]

    for entry in files:
        src = folder_bytes[entry.folder_index]
        payload = src[entry.offset : entry.offset + entry.size]
        if len(payload) != entry.size:
            raise ValueError(f"Truncated file payload for {entry.name}")
        dest = output_dir / entry.name.replace("\\", "/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cab", type=Path, help="Path to .cab file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output directory (defaults to <cab stem>)",
    )
    args = parser.parse_args()

    output_dir = args.output or args.cab.with_suffix("")
    extract(args.cab, output_dir)
    print(output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
