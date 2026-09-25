#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
game_dir="$repo_dir/runtime/experiments/engine-seed-game"
wine_prefix="$repo_dir/runtime/experiments/rng-wineprefix"

if [[ ! -f "$game_dir/BookwormAdventures.exe" ]]; then
  echo "Build the fixed-seed experiment copy first." >&2
  exit 1
fi

export WINEPREFIX="$wine_prefix"
export WINEDEBUG=-all
wine reg add 'HKCU\Software\Wine\Explorer' /v Desktop \
  /t REG_SZ /d BookwormRNGExperiment /f >/dev/null
wine reg add 'HKCU\Software\Wine\Explorer\Desktops' \
  /v BookwormRNGExperiment /t REG_SZ /d 800x600 /f >/dev/null

cd "$game_dir"
wine "$game_dir/BookwormAdventures.exe" </dev/null 2>&1 | tee "$game_dir/lua.log"
