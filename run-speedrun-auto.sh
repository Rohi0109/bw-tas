#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$repo_dir/speedrun${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$repo_dir/speedrun/continuous_runner.py" \
  --log "$repo_dir/runtime/stage/lua.log" "$@"
