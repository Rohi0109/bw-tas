#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
game_dir="$repo_dir/runtime/deluxe-modded"
game_exe="$game_dir/BookwormAdventures.exe"
wine_prefix="$repo_dir/runtime/wineprefix"

if [[ ! -f "$game_exe" ]]; then
  echo "Deluxe TAS copy is not prepared. Run ./prepare-deluxe-tas.sh first." >&2
  exit 1
fi

cd "$game_dir"
: > "$game_dir/lua.log"
env WINEPREFIX="$wine_prefix" WINEDEBUG=-all \
  wine reg add 'HKCU\Software\Wine\Explorer' /v Desktop \
  /t REG_SZ /d BookwormDeluxeTAS /f >/dev/null
env WINEPREFIX="$wine_prefix" WINEDEBUG=-all \
  wine reg add 'HKCU\Software\Wine\Explorer\Desktops' \
  /v BookwormDeluxeTAS /t REG_SZ /d 800x600 /f >/dev/null
env WINEPREFIX="$wine_prefix" WINEDEBUG=-all wine "$game_exe" </dev/null \
  2>&1 | tee "$game_dir/lua.log"
