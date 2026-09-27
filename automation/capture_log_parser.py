"""Parser for the combined GDB+Lua game log from parent-launched Wine capture.

Both the GDB output and the game's Lua print() calls go to the same file in
the parent-launch path. This module extracts AUTOMATION_SIM_* records,
deduplicates, quarantines ambiguous or truncated blocks, and skips Wine
console noise.

Record format emitted by DumpSimulationState.lua:
  AUTOMATION_SIM_BEGIN=<id>|E
  AUTOMATION_SIM_CREATURE=<id>|<owner>|<field>|<value>|E
  AUTOMATION_SIM_ATTACK=<id>|<owner>|<key>|<field>|<value>|E
  AUTOMATION_SIM_EFFECT=<id>|<owner>|<key>|<field>|<value>|E
  AUTOMATION_SIM_UNSUPPORTED=<id>|<owner>|<reason>|E
  AUTOMATION_SIM_END=<id>|E
"""
import re
from typing import Iterable, Optional
from dataclasses import dataclass, field

_PREFIX = 'AUTOMATION_SIM_'
_BEGIN_RE = re.compile(r'^AUTOMATION_SIM_BEGIN=(\d+)\|E$')
_END_RE = re.compile(r'^AUTOMATION_SIM_END=(\d+)\|E$')
_FIELD_RE = re.compile(r'^AUTOMATION_SIM_(\w+)=(.+)\|E$')
_CONSOLE_RE = re.compile(r'^\x1b\[|\r$')


@dataclass
class ParsedRecord:
    attack_id: int
    fields: dict
    quarantine_reason: Optional[str] = None


def _clean_line(raw: str) -> str:
    """Normalise a raw log line: strip trailing whitespace, unescape literal \\n."""
    return raw.rstrip().replace('\\n', '\n')


def _is_noise(line: str) -> bool:
    """True for Wine console redraw sequences and blank lines."""
    if not line:
        return True
    if line == '\r' or _CONSOLE_RE.match(line):
        return True
    return False


def parse_sim_log(lines: Iterable[str]) -> list[ParsedRecord]:
    """Parse sim log lines and return all ParsedRecords (good and quarantined)."""
    records: list[ParsedRecord] = []
    seen_ids: set[int] = set()
    max_seen_id: Optional[int] = None

    pending_id: Optional[int] = None
    pending_fields: dict = {}
    pending_rows: list[str] = []

    def flush_pending(reason: Optional[str]) -> None:
        nonlocal pending_id, pending_fields, pending_rows
        if pending_id is not None:
            records.append(ParsedRecord(
                attack_id=pending_id,
                fields={k: v for k, v in pending_fields.items()
                        if not (isinstance(k, str) and k.startswith('_'))},
                quarantine_reason=reason,
            ))
        pending_id = None
        pending_fields = {}
        pending_rows = []

    for raw in lines:
        line = _clean_line(raw)
        if _is_noise(line):
            continue
        if not line.startswith(_PREFIX):
            continue

        begin_m = _BEGIN_RE.match(line)
        if begin_m:
            attack_id = int(begin_m.group(1))
            if pending_id is not None:
                # Previous block was not closed — truncated
                flush_pending('truncated: BEGIN without END')
            # Session restart: new id is lower than the highest we've seen
            if max_seen_id is not None and attack_id < max_seen_id:
                # Quarantine everything accumulated so far with the old id, if any
                # (already flushed above if there was a pending)
                # Mark the new block as a session restart — will quarantine on commit
                pending_id = attack_id
                pending_fields = {}
                pending_rows = [line]
                pending_fields['_session_restart'] = True
            else:
                pending_id = attack_id
                pending_fields = {}
                pending_rows = [line]
            continue

        end_m = _END_RE.match(line)
        if end_m:
            end_id = int(end_m.group(1))
            if pending_id is None:
                # END without BEGIN
                records.append(ParsedRecord(
                    attack_id=end_id,
                    fields={},
                    quarantine_reason='truncated: END without BEGIN',
                ))
                continue
            if end_id != pending_id:
                # Conflicting IDs — quarantine this block
                flush_pending(f'ambiguous boundary: BEGIN id={pending_id} END id={end_id}')
                continue

            attack_id = pending_id
            reason: Optional[str] = None

            if pending_fields.get('_session_restart'):
                reason = 'session restart: attack_id below previous maximum'
            elif attack_id in seen_ids:
                reason = f'duplicate attack_id={attack_id}'

            if reason is None:
                seen_ids.add(attack_id)
                if max_seen_id is None or attack_id > max_seen_id:
                    max_seen_id = attack_id

            records.append(ParsedRecord(
                attack_id=attack_id,
                fields={k: v for k, v in pending_fields.items()
                        if not (isinstance(k, str) and k.startswith('_'))},
                quarantine_reason=reason,
            ))
            pending_id = None
            pending_fields = {}
            pending_rows = []
            continue

        # Other AUTOMATION_SIM_ lines inside a block
        field_m = _FIELD_RE.match(line)
        if field_m and pending_id is not None:
            kind = field_m.group(1)
            rest = field_m.group(2)
            parts = rest.split('|')
            # First part is the attack id; verify it matches
            try:
                row_id = int(parts[0])
            except (ValueError, IndexError):
                pending_fields.setdefault('_parse_errors', []).append(line)
                continue
            if row_id != pending_id:
                pending_fields.setdefault('_id_mismatches', []).append(line)
                continue
            key = (kind,) + tuple(parts[1:])
            if key in pending_fields:
                pending_fields.setdefault('_duplicates', []).append(line)
            else:
                pending_fields[key] = True

    # Any unclosed pending block at EOF
    if pending_id is not None:
        flush_pending('truncated: BEGIN without END at EOF')

    return records


def partition_sim_log(
    records: list[ParsedRecord],
) -> tuple[list[ParsedRecord], list[ParsedRecord]]:
    """Split records into (good, quarantined)."""
    good = [r for r in records if r.quarantine_reason is None]
    quarantined = [r for r in records if r.quarantine_reason is not None]
    return good, quarantined
