#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Build/rebuild the disposable modded Deluxe TAS copy.
exec python3 "$repo_dir/automation/prepare_deluxe.py" "$@"
