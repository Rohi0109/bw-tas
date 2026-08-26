set shell := ["bash", "-euo", "pipefail", "-c"]

# Show the available Bookworm launch and automation recipes.
default:
    @just --list

# Build/rebuild the disposable modded Deluxe TAS copy.
prepare-deluxe *args:
    ./prepare-deluxe-tas.sh {{args}}

# Open Bookworm Adventures Deluxe in its 800x600 Wine desktop.
deluxe *args:
    ./run-deluxe-tas.sh {{args}}

# Run the Deluxe solver; pass flags after `--`, e.g. `just deluxe-auto -- --strategy max-damage`.
deluxe-auto *args:
    ./run-deluxe-speedrun-auto.sh {{args}}

# Open the source/launcher build through Wine.
bookworm *args:
    ./run-native.sh {{args}}

# Run the Deluxe continuous TAS solver (alias with the expected generic name).
speedrun-auto *args:
    ./run-deluxe-speedrun-auto.sh {{args}}

# Run the legacy continuous solver for the source/launcher build.
source-auto *args:
    ./run-speedrun-auto.sh {{args}}

# Solve one board against the source build.
source-turn *args:
    ./run-speedrun-turn.sh {{args}}

# Run the optimizer and log-state regression tests.
test:
    PYTHONPATH=speedrun python3 -m unittest discover -s speedrun/tests -p 'test_*.py' -v

# Audit every distinct live Deluxe enemy name recorded in lua.log.
audit-enemies:
    PYTHONPATH=speedrun python3 speedrun/audit_enemy_names.py
