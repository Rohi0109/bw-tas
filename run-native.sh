#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
wine_prefix="$repo_dir/runtime/launcher-wineprefix"
game_exe="$repo_dir/runtime/stage/bwa_launcher.exe"

exec env WINEPREFIX="$wine_prefix" WINEDEBUG=-all wine "$game_exe"
