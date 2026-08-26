set shell := ["bash", "-euo", "pipefail", "-c"]

# Show the short command list below.
default:
    @just --list

# Build or rebuild the disposable modded Deluxe TAS game.
setup *args:
    ./prepare-deluxe-tas.sh {{args}}

# Launch the modded Deluxe game. Keep this terminal open.
game *args:
    ./run-deluxe-tas.sh {{args}}

# Run the Deluxe TAS in a second terminal, e.g. `just tas --strategy max-damage`.
tas *args:
    ./run-deluxe-speedrun-auto.sh {{args}}

# Launch the experimental source/launcher build.
source-game *args:
    ./run-native.sh {{args}}

# Run continuous automation against the experimental source build.
source-tas *args:
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
