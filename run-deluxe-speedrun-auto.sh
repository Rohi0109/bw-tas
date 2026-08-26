#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
log_path="$repo_dir/runtime/deluxe-modded/lua.log"

if [[ ! -f "$log_path" ]]; then
  echo "No Deluxe lua.log yet. Start ./run-deluxe-tas.sh and enter a battle first." >&2
  exit 1
fi

export PYTHONPATH="$repo_dir/speedrun${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$repo_dir/speedrun/continuous_runner.py" \
  --log "$log_path" \
  --title "Bookworm Adventures Deluxe" \
  --layout deluxe \
  "$@"
