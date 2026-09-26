# Bookworm Adventures Deluxe TAS

The live TAS reads instrumented Lua events, chooses a word, and sends native
X11 input to the Wine game. Telemetry reports what happened; the solver predicts
what to play; the runner decides when input is safe. These are separate jobs.

## Run

Run commands from the repository root. The Deluxe setup requires the game
assets, Wine, Python dependencies, and an X11 display.

```sh
just setup       # build/rebuild the disposable instrumented Deluxe copy
just game        # launch it; keep this terminal open
# In another terminal:
just tas         # attach to the current game, without recreating the profile
```

For a fresh timed run, leave Deluxe at its main menu and use `just tas-new`.
**This deletes and recreates the selected TAS profile.** It preloads the solver
before profile confirmation. `just new-run` is the separate profile-reset tool;
do not run it merely to resume. Stop automation with Ctrl-C. Do not run two
controllers against the same game.

`just rng-game` and `just rng-tas` target a separate experimental installation
and Wine prefix. Experiment mode records session identities and disables race
record updates. A directory named `engine-seed-game` does not prove the reset
hook is installed: verify native `AUTOMATION_RNG_RESET` markers. See
[STATE_GRAPH.md](STATE_GRAPH.md) for the current installation caveat and RNG work.

## Architecture: where to edit

Start at **[tas.py](tas.py)**. Its main function reads settings, configures
logging, claims exclusive control, prepares the game, and follows it until
finished. `just tas`, `just tas-new`, and `just rng-tas` use this entry point.
`tas_settings.py` owns command-line defaults and validation. The older
`continuous_runner.py` command remains compatible.

```text
Game Lua hooks -> lua.log -> telemetry parsers -> DeluxeState
                                                    |
                          dictionary -> solver -> Candidate
                                                    |
                              combat/route policy -> runner
                                                    |
                                            X11 controller -> game
```

| Responsibility | Files | Boundary |
|---|---|---|
| Native observations | `../automation/lua_hook/`, `../automation/prepare_deluxe.py` | Emits state/input ownership events; hook changes need rebuild and game restart. |
| Shared values | `combat_models.py` | Immutable `DeluxeState`, `Candidate`, `WordSpec`; no I/O or policy. |
| Combat snapshot parsing | `combat_telemetry.py` | Lua text to the latest complete sequence-tagged state; no solving or clicks. |
| Navigation/status event parsing | `runner_telemetry.py` | Event patterns, log recovery, dialogue and incapacitation observations; no input. |
| Word search and scoring | `deluxe_optimizer.py` | Dictionary index, playable paths, modeled damage, animation cost and candidate ranking. |
| Combat decisions | `combat_policy.py` | Healing, Power-Up, Purify, boss-finisher strategy and Sphinx answers; no clicks. |
| Attack lifecycle | `attack_lifecycle.py`, `attack_input.py` | Pending submission state, acknowledgement/retry/cancellation transitions, and the native selection/Enter handshake. Navigation state stays outside this object. |
| Recorded lookahead | `book1_optimizer.py`, `rack_prefetch.py` | Exact-state corpus/overrides and cached candidates; not a complete RNG simulator. |
| Route decisions | `deluxe_route.py` | Enemy identity and reset eligibility. Some navigation policy still resides in the runner. |
| Application | `tas.py`, `tas_settings.py` | Readable lifecycle, explicit lock cleanup, CLI defaults and validation. |
| Coordination | `continuous_runner.py` | `prepare_game` returns a typed `PreparedSession`; `follow_game_until_finished` owns the event loop, guards, retries and transitions. |
| Input | `x11_controller.py`, `menu_runner.py` | Native keyboard/mouse and calibrated UI actions; no word selection policy. |
| Startup and timing | `new_run.py`, `run_timer.py`, `experiment_session.py` | Profile lifecycle, chapter timing and experiment provenance. |
| Logging | `runner_logging.py` | Shared message formatting for orchestration and input helpers. |
| Legacy single-board entry | `live_runner.py` | Older board-only solver bridge and CLI; not the continuous Deluxe solver. |

For a bad damage estimate, start in `deluxe_optimizer.py`. For an incomplete or
stale snapshot, start in `combat_telemetry.py` and the Lua hooks. For a correct
word sent at the wrong time, inspect `continuous_runner.py` and the input
acknowledgements. For potion choices, start in `combat_policy.py`.

Existing imports of models/parsers through `deluxe_optimizer` and controllers
through `live_runner` remain compatible. New code should use their owning
modules directly. Do not introduce dependencies from models or telemetry back
into the solver, controller, or runner.

## Logs and evidence

Normal runs use `runtime/deluxe-modded/` (relative to the repository root):

- `lua.log`: native observations, including sequence-tagged snapshots and attack IDs.
- `tas-live.log`: runner decisions, retries and navigation messages.
- `tas-timing.jsonl`: structured timing and combat observations.
- `run-timer.json`: current run timer; persistent results live under `records/`.

Keep run/session identities when comparing traces. A submitted word is not a
confirmed attack; zero enemy HP is not proof of a save-safe reset. Do not reuse
an observed refill as the predicted outcome of an unplayed word. Predicted
animation costs are empirical wall-time estimates, not an exact frame simulator.

## Tests and safe changes

```sh
PYTHONPATH=speedrun python3 -m unittest discover -s speedrun/tests -q
PYTHONPATH=speedrun python3 speedrun/tas.py --help
```

These checks do not require launching the game. Add regression fixtures for
telemetry and policy changes; use fake controllers for input tests. A passing
unit suite is not native timing validation. Preserve READY freshness, complete
selection checks, attack acknowledgements, reset guards and single-runner locks.
Do not change polling delays, route choices or damage formulas during a
structural refactor.

The first cleanup pass separates parsing, models, combat policy and input.
The attack lifecycle now owns submission fields and its acknowledgement,
retry and overlay-cancellation transitions. The continuous event loop is still
large. Follow-up work should extract its navigation state, then separate
telemetry recording from orchestration. Splitting the loop solely to meet a
line-count target risks obscuring shared ownership state.

## Quiet local monitoring (no model calls)

Launch `just game`, then in another terminal use **`just monitor` instead of
`just tas`**. It starts one runner attached to the current game; it does not
reset the profile. Do not leave another TAS runner active.

```sh
just monitor          # stays running locally; only prints its terminal outcome
just monitor-status   # in another terminal: read the compact status snapshot
```

This mode does not invoke Codex, take screenshots, repair files, restart the
game, or recreate profiles. The ordinary runner still appends its detailed
logs. Every five seconds the monitor atomically refreshes
`runtime/diagnostics/monitor-status.json` with the latest observed state,
chapter, attack/warning counts, elapsed time and terminal outcome. These are
observed runner messages, not proof of kills or campaign completion.

The monitor stops its owned runner on 60 seconds without Lua-log changes or a
two-hour process timeout. It also catches nonzero runner exits. Failures save a
bounded diagnostic packet under `runtime/incidents/`; the status file links to
it. Ctrl-C stops the monitor's child runner, not the independently launched
game. The timeout measures log activity, not semantic progress: a loop that
keeps writing can evade the idle detector until the hard timeout. An exit with
code zero may be an intentional inspection stop, not a completed campaign.
Check the snapshot timestamp if the monitor itself was forcibly killed.

This local process does **not** wake an existing chat automatically. Share the
terminal result or ask for a status check, and the assistant can read the small
snapshot first instead of repeatedly ingesting full logs. Running it locally
avoids model polling; there is no promise that an AI-assisted diagnosis is free.

The existing `just watchdog` is a different, opt-in auto-repair mode: it can
invoke Codex and edit/retry the runner. Its prompt's token request is not a
hard usage cap. Keep it separate from this no-model monitor. OpenAI documents
scripted invocation through [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode);
that is useful for a future bounded escalation, not necessary for local checks.

Monitor regression checks (fake child processes; no live game needed):

```sh
PYTHONPATH=automation python3 -m unittest automation/test_watchdog.py -q
```

## Further reading

- [In-house simulator and fidelity ledger](SIMULATOR.md)
- [Project roadmap](../things-to-add-roadmap.md)
- [RNG and deterministic graph experiments](STATE_GRAPH.md)
- [Transition and damage validation](TRANSITION_BASELINE.md)
- [Historical notes](HISTORICAL_NOTES.md) — preserved experiments, not current defaults
