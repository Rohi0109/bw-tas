# TAS watchdog

Run the fully automated TAS repair loop from the repository root:

```bash
just watchdog
```

Runner options are forwarded, for example `just watchdog --strategy max-damage`.
If the log remains unchanged for 20 seconds, this command stops the runner,
creates an incident, launches one bounded Codex repair, and restarts the TAS
only when Codex reports that the patch is safe to retry. It stops after three
attempts for an identical incident.

At the stall boundary it also captures the focused game window as a PNG beside
the JSON incident and attaches that image to Codex. Use `--no-screenshot` with
the Python supervisor directly if desktop capture is undesirable.

To detect one stall without invoking Codex, run `just watchdog-once`.

The watchdog exits normally when the command exits normally. If `lua.log` does
not change for 20 seconds, it terminates the command group, exits with status
124, and writes a bounded incident to `runtime/incidents/`.

Add a total wall-clock limit when useful:

```bash
python3 automation/tas_watchdog.py \
  --log runtime/deluxe-modded/lua.log \
  --stall-seconds 20 \
  --timeout-seconds 3600 \
  -- ./run-deluxe-speedrun-auto.sh
```

Preview the bounded Codex repair invocation for an incident:

```bash
just repair runtime/incidents/stall-TIMESTAMP.json
```

Launch one repair attempt explicitly:

```bash
just repair-run runtime/incidents/stall-TIMESTAMP.json
```

Repair attempts are deduplicated by incident signature and capped at three.
Codex receives only the incident packet, not the complete campaign log. Its
structured result is written beside the incident as `*.codex-result.json`.

The nested Codex repair uses `danger-full-access` because this host's bubblewrap
sandbox cannot initialize its loopback interface. Full automation therefore
grants the repair agent host filesystem and process access. Keep this recipe
limited to a trusted local repository and trusted incident inputs.
