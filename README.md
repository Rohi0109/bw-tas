# Bookworm Adventures TAS

This repository contains the tooling and notes for an automated **Bookworm
Adventures Deluxe** tool-assisted speedrun. The runner reads game telemetry,
chooses words, sends native input through X11, and records timing and combat
evidence.

The active repository is
[Rohi0109/bw-tas](https://github.com/Rohi0109/bw-tas).

## Quick start

Run commands from the repository root.

```sh
just setup
just game
```

Keep the game terminal open. In a second terminal, attach the runner:

```sh
just tas
```

For a fresh timed profile, leave the game at its main menu and run:

```sh
just tas-new
```

This recreates the selected TAS profile. Use `just tas` to resume an existing
profile without resetting it.

The isolated RNG experiment uses separate commands and installation files:

```sh
just rng-game
just rng-tas
```

Do not run two input controllers against the same game window.

## What is here

| Path | Purpose |
| --- | --- |
| `speedrun/tas.py` | Main TAS entry point and lifecycle setup. |
| `speedrun/continuous_runner.py` | Event loop for combat, navigation, retries, and transitions. |
| `speedrun/deluxe_optimizer.py` | Word search, damage modeling, and candidate ranking. |
| `speedrun/combat_policy.py` | Potion, boss, status, and route decisions. |
| `speedrun/x11_controller.py` | Calibrated keyboard and mouse input. |
| `automation/lua_hook/` | Instrumentation hooks that emit native game events. |
| `runtime/` | Local game copies, logs, and experiment output; ignored by Git. |
| `records/` | Versioned timing and run history. |

For module boundaries, telemetry format, and detailed run instructions, see
[`speedrun/README.md`](speedrun/README.md).

## Validation

Run the Python regression suites without launching the game:

```sh
PYTHONPATH=speedrun python3 -m unittest discover -s speedrun/tests -p 'test_*.py'
python3 -m unittest discover -s automation -p 'test_*.py'
```

These tests cover parser behavior, solver and policy decisions, input guards,
navigation state, telemetry, and watchdog behavior. Passing tests do not
replace live timing validation.

## Current task

The active optimization task is faster, reliable menu exit and re-entry. The
legacy reset path remains the default while native menu ownership observations
are validated. The implementation plan and acceptance criteria are in
[`speedrun/MENU_RESET_HANDOFF.md`](speedrun/MENU_RESET_HANDOFF.md).

The repository does not claim a completed menu-reset speedup until controlled
game runs show improved reset-to-READY timing without lost progress or reset
failures.

## Related documentation

- [`speedrun/README.md`](speedrun/README.md) — detailed architecture and usage.
- [`speedrun/MENU_RESET_HANDOFF.md`](speedrun/MENU_RESET_HANDOFF.md) — current implementation handoff.
- [`speedrun/STATE_GRAPH.md`](speedrun/STATE_GRAPH.md) — deterministic graph and RNG experiments.
- [`things-to-add-roadmap.md`](things-to-add-roadmap.md) — broader roadmap.

The game assets and executable builds remain subject to their original rights.
Use and distribute them only where you have permission.
