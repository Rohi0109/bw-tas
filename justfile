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

# Launch the fixed-seed experiment in its own 800x600 Wine desktop and prefix.
rng-game:
    bash ./run-rng-game.sh

# Run the fixed-seed TAS with session IDs, separate telemetry and no race timer.
rng-tas *args:
    PYTHONPATH=speedrun python3 speedrun/tas.py \
      --layout deluxe --experiment \
      --title "Bookworm Adventures Deluxe" \
      --log runtime/experiments/engine-seed-game/lua.log \
      --log-file runtime/experiments/engine-seed-game/tas-live.log {{args}}

# Run the Deluxe TAS in a second terminal, e.g. `just tas --strategy max-damage`.
tas *args:
    ./run-deluxe-speedrun-auto.sh {{args}}

# Preload the solver, recreate the active TAS profile, then run in one process.
# Start with Deluxe at its main menu. This deletes/recreates the selected profile.
tas-new *args:
    ./run-deluxe-speedrun-auto.sh --new-run {{args}}

# Run the TAS; automatically ask Codex to repair stalls and safely restart.
watchdog *args:
    python3 automation/auto_repair_loop.py \
      --log runtime/deluxe-modded/lua.log \
      --stall-seconds 20 \
      -- ./run-deluxe-speedrun-auto.sh {{args}}

# Quiet local monitoring: no screenshots, model calls, repairs, or restarts.
# Launch the game first; attaches to its current state without deleting a profile.
monitor *args:
    python3 automation/tas_watchdog.py \
      --log runtime/deluxe-modded/lua.log --no-screenshot --quiet \
      --status runtime/diagnostics/monitor-status.json \
      --stall-seconds 60 --timeout-seconds 7200 \
      -- ./run-deluxe-speedrun-auto.sh {{args}}

# Show the last local monitor snapshot; this does not invoke a model.
monitor-status:
    python3 -m json.tool runtime/diagnostics/monitor-status.json

# Run one watched TAS attempt without automatically invoking Codex.
watchdog-once *args:
    python3 automation/tas_watchdog.py \
      --log runtime/deluxe-modded/lua.log \
      --stall-seconds 20 \
      -- ./run-deluxe-speedrun-auto.sh {{args}}

# Preview the bounded Codex repair for a watchdog incident.
repair packet:
    python3 automation/repair_loop.py "{{packet}}"

# Execute one bounded Codex repair for a watchdog incident.
repair-run packet:
    python3 automation/repair_loop.py "{{packet}}" --execute

# From the Deluxe main menu, enter Adventure and the current chapter.
menu-start *args:
    PYTHONPATH=speedrun python3 speedrun/menu_runner.py start {{args}}

# Explicitly run the WR battle-menu reset sequence (not yet route-triggered).
menu-reset *args:
    PYTHONPATH=speedrun python3 speedrun/menu_runner.py reset {{args}}

# Delete and recreate only the current Lex10 TAS profile, then skip its intro.
new-run *args:
    PYTHONPATH=speedrun python3 speedrun/new_run.py {{args}}

# Optional standalone watcher; `just tas` records the timer automatically.
timer *args:
    PYTHONPATH=speedrun python3 speedrun/run_timer.py watch {{args}}

# Print current chapter times and gaps to the human WR target.
timer-report:
    PYTHONPATH=speedrun python3 speedrun/run_timer.py report

# Print every archived run separately; personal-best splits remain in `just wr`.
run-history:
    PYTHONPATH=speedrun python3 speedrun/run_timer.py history

# Short alias for the live human-WR comparison report.
wr:
    PYTHONPATH=speedrun python3 speedrun/run_timer.py update-best
    PYTHONPATH=speedrun python3 speedrun/run_timer.py report

# Diagnose Book 1 split loss, combat time, and clean transition coverage.
book1-report:
    PYTHONPATH=speedrun python3 speedrun/book1_report.py

# Run the opt-in validated-transition strategy (falls back safely when sparse).
tas-book1-lookahead *args:
    ./run-deluxe-speedrun-auto.sh --strategy book1-lookahead {{args}}

# Experimental speed policy: target Sapphire, then minimize attack class/input.
tas-speed-sapphire *args:
    ./run-deluxe-speedrun-auto.sh --strategy speed-sapphire {{args}}

# Summarize measured kill/animation costs for solver simulations.
animation-report *args:
    PYTHONPATH=speedrun python3 speedrun/animation_report.py {{args}}

# Replay a fresh seed-1 run with exact state-fingerprint decision overrides.
tas-book1-experiment decisions *args:
    ./run-deluxe-speedrun-auto.sh --book1-overrides "{{decisions}}" {{args}}

# Stop the timer and print its final split report.
timer-finish:
    PYTHONPATH=speedrun python3 speedrun/run_timer.py finish

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
