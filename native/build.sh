#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "$script_dir/.." && pwd)"
toolchain="$repo_dir/runtime/toolchain/usr"
compiler="$toolchain/bin/i686-w64-mingw32-gcc-win32"

if [[ ! -x "$compiler" ]]; then
  echo "Missing local MinGW compiler. See README.md for setup." >&2
  exit 1
fi

PATH="$toolchain/bin:$PATH" "$compiler" -mwindows -O2 -s \
  -isystem "$toolchain/i686-w64-mingw32/include" \
  -B"$toolchain/i686-w64-mingw32/bin/" \
  -B"$toolchain/lib/gcc/i686-w64-mingw32/13-win32/" \
  -L"$toolchain/i686-w64-mingw32/lib" \
  -o "$script_dir/bwa_launcher.exe" "$script_dir/bwa_launcher.c"
echo "Built $script_dir/bwa_launcher.exe"
