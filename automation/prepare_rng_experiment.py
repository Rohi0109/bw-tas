"""Create a separate fixed-seed executable for RNG experiments; never launch it.

For this exact Deluxe build, force the CRT srand argument to 1. This controls
seeding only, not call ordering, thread scheduling, or checkpoint restoration.
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = 'BookwormAdventures.exe'
EXPECTED_SHA256 = '7fa527a59ff1108b98b0d18b0625d280029c0fd6c5fb3f91bb2f168b95968c67'
# srand: call CRT thread data; mov ecx,[esp+4]; mov [eax+14h],ecx; ret.
SIGNATURE = bytes.fromhex('e8 db bb 00 00 8b 4c 24 04 89 48 14 c3')


def fixed_seed_executable(data):
    if hashlib.sha256(data).hexdigest() != EXPECTED_SHA256:
        raise ValueError('Unrecognized executable; native patch needs revalidation')
    if data.count(SIGNATURE) != 1:
        raise ValueError('Expected exactly one validated srand implementation')
    offset = data.index(SIGNATURE) + 5
    # xor ecx,ecx; inc ecx; nop. Same footprint, stack and return convention.
    patched = data[:offset] + bytes.fromhex('31 c9 41 90') + data[offset+4:]
    return patched, offset


def prepare(source, output):
    source, output = source.resolve(), output.resolve()
    if output.exists() or source == output or source in output.parents:
        raise ValueError('Use a new destination outside the source installation')
    original = (source/EXECUTABLE).read_bytes()
    patched, offset = fixed_seed_executable(original)
    # Only static installation content: exclude user telemetry, experiment
    # output, caches and the private pristine archive used by normal builds.
    shutil.copytree(source, output, ignore=shutil.ignore_patterns(
        '*.log', '*.json', '*.jsonl', '.tas-*', '*.lock', '__pycache__',
    ))
    (output/EXECUTABLE).write_bytes(patched)
    manifest = dict(
        purpose='fixed-seed experiment only', seed=1,
        source_executable_sha256=hashlib.sha256(original).hexdigest(),
        experiment_executable_sha256=hashlib.sha256(patched).hexdigest(),
        main_pak_sha256=hashlib.sha256((output/'main.pak').read_bytes()).hexdigest(),
        file_offset=offset, original_bytes=original[offset:offset+4].hex(),
        replacement_bytes=patched[offset:offset+4].hex(),
        limitations=[
            'Every native srand call on every thread is forced to seed 1.',
            'Existing threads retain their RNG state until srand executes.',
            'Random call ordering and elapsed ticks remain uncontrolled.',
            'A saved profile does not restore process memory or the RNG cursor.',
            'Use a separate Wine prefix and disposable profile for trials.',
            'No trial or normal-route validation has been performed by this builder.',
        ],
    )
    (output/'rng-experiment.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'runtime/deluxe-modded')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output), indent=2))


if __name__ == '__main__':
    main()
