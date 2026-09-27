"""Capture engine RNG entry/return states from an explicitly selected Wine PID."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

EXE_HASH = '7fa527a59ff1108b98b0d18b0625d280029c0fd6c5fb3f91bb2f168b95968c67'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--game-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--draws', type=int, default=100)
    args = parser.parse_args()
    if args.pid < 1 or not 1 <= args.draws <= 10000:
        parser.error('positive PID and 1..10000 draws required')
    if args.output.exists():
        parser.error('Output must be a new file')
    game = args.game_dir.resolve()
    build = {name: hashlib.sha256((game/name).read_bytes()).hexdigest()
             for name in ('BookwormAdventures.exe', 'main.pak')}
    if build['BookwormAdventures.exe'] != EXE_HASH:
        parser.error('Unsupported executable build')
    # Do not attach to an unrelated process with an accidentally matching address.
    maps = Path(f'/proc/{args.pid}/maps').read_text()
    if str(game/'BookwormAdventures.exe') not in maps:
        parser.error('PID does not map the specified executable')
    env = dict(os.environ, BWA_CAPTURE_DRAWS=str(args.draws),
               BWA_CAPTURE_OUTPUT=str(args.output.resolve()), BWA_CAPTURE_BUILD=json.dumps(build))
    script = Path(__file__).with_name('capture_native_rng_gdb.py')
    result = subprocess.run(['gdb','--nx','--quiet','--batch','-p',str(args.pid),
                             '-ex','set pagination off','-ex',f'source {script}'], env=env)
    if result.returncode:
        return result.returncode
    # GDB can exit zero after a sourced Python script raises an exception.
    if not args.output.exists():
        return 1
    try:
        with args.output.open() as stream:
            final = None
            for line in stream:
                final = json.loads(line)
        return 0 if final and final.get('kind') == 'end' and final.get('complete') is True else 1
    except (OSError, ValueError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
