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

Quarantine triggers (all produce a non-None quarantine_reason):
  - BEGIN without END (truncated block)
  - END without BEGIN
  - BEGIN/END id mismatch (ambiguous boundary)
  - Duplicate attack_id (keep first, quarantine repeat)
  - attack_id below highest seen (session restart)
  - Any field row whose embedded id differs from the block's BEGIN id
  - Any field row with a conflicting value for the same (kind, owner, ...) key
  - Any UNSUPPORTED marker inside the block
  - Any parse errors (malformed row)
"""
import re
from dataclasses import dataclass, field as dc_field
from typing import Iterable, Optional

_PREFIX = 'AUTOMATION_SIM_'
_BEGIN_RE = re.compile(r'^AUTOMATION_SIM_BEGIN=(\d+)\|E$')
_END_RE = re.compile(r'^AUTOMATION_SIM_END=(\d+)\|E$')
_FIELD_RE = re.compile(r'^AUTOMATION_SIM_(\w+)=(.+)\|E$')
_ANSI_RE = re.compile(r'^\x1b\[[0-9;]*[A-Za-z]')
_LEADING_CTRL_RE = re.compile(r'^[\x00-\x09\x0b-\x1f\x7f]+')


@dataclass
class ParsedRecord:
    attack_id: int
    fields: dict        # canonical_key → value string; empty on quarantine
    quarantine_reason: Optional[str] = None


def _split_raw_line(raw: str) -> list[str]:
    """Unescape console-escaped sequences and split into logical sub-lines.

    Handles \\r\\n, \\r, and \\n escape sequences that Wine's console framing
    embeds into a single log line, producing multiple logical records per raw
    input line.  Returns only non-empty sub-lines.
    """
    cleaned = raw.rstrip()
    cleaned = (cleaned.replace('\\r\\n', '\n')
                      .replace('\\r', '\n')
                      .replace('\\n', '\n'))
    return [s for s in cleaned.split('\n') if s]


def _apply_backspaces(s: str) -> str:
    """Simulate terminal line-buffer: each \\x08 (backspace) erases the preceding char."""
    buf = []
    for ch in s:
        if ch == '\b':
            if buf:
                buf.pop()
        else:
            buf.append(ch)
    return ''.join(buf)


def _strip_prefix_noise(line: str) -> str:
    """Strip ANSI escapes, simulate backspace erasure, then leading control chars."""
    line = _ANSI_RE.sub('', line)
    line = _apply_backspaces(line)
    line = _LEADING_CTRL_RE.sub('', line)
    return line


def _is_noise(line: str) -> bool:
    """True for blank lines and Wine console redraw sequences."""
    if not line:
        return True
    if line == '\r':
        return True
    return False


def parse_sim_log(lines: Iterable[str]) -> list[ParsedRecord]:
    """Parse sim log lines and return all ParsedRecords (good and quarantined).

    Strips leading ANSI escapes before checking for _PREFIX so that
    console-prefixed AUTOMATION_SIM lines are recovered rather than silently
    dropped.  All quarantine reasons are explicit strings; callers can split
    with partition_sim_log().
    """
    records: list[ParsedRecord] = []
    seen_ids: set[int] = set()
    max_seen_id: Optional[int] = None

    pending_id: Optional[int] = None
    pending_fields: dict = {}       # canonical_key → value string
    pending_errors: list[str] = []  # accumulated quarantine reasons within block

    def flush_pending(reason: Optional[str]) -> None:
        nonlocal pending_id, pending_fields, pending_errors
        if pending_id is not None:
            all_reasons = ([reason] if reason else []) + pending_errors
            records.append(ParsedRecord(
                attack_id=pending_id,
                fields=dict(pending_fields) if not all_reasons else {},
                quarantine_reason='; '.join(all_reasons) if all_reasons else None,
            ))
        pending_id = None
        pending_fields = {}
        pending_errors = []

    for raw in lines:
        for line in _split_raw_line(raw):
            line = _strip_prefix_noise(line)
            if _is_noise(line):
                continue
            if not line.startswith(_PREFIX):
                continue

            begin_m = _BEGIN_RE.match(line)
            if begin_m:
                attack_id = int(begin_m.group(1))
                if pending_id is not None:
                    flush_pending('truncated: BEGIN without END')
                pending_id = attack_id
                pending_fields = {}
                pending_errors = []
                if max_seen_id is not None and attack_id < max_seen_id:
                    pending_errors.append('session restart: attack_id below previous maximum')
                continue

            end_m = _END_RE.match(line)
            if end_m:
                end_id = int(end_m.group(1))
                if pending_id is None:
                    records.append(ParsedRecord(
                        attack_id=end_id,
                        fields={},
                        quarantine_reason='truncated: END without BEGIN',
                    ))
                    continue
                if end_id != pending_id:
                    flush_pending(f'ambiguous boundary: BEGIN id={pending_id} END id={end_id}')
                    continue

                attack_id = pending_id
                if attack_id in seen_ids:
                    pending_errors.append(f'duplicate attack_id={attack_id}')

                if not pending_errors:
                    seen_ids.add(attack_id)
                    if max_seen_id is None or attack_id > max_seen_id:
                        max_seen_id = attack_id

                records.append(ParsedRecord(
                    attack_id=attack_id,
                    fields=dict(pending_fields) if not pending_errors else {},
                    quarantine_reason='; '.join(pending_errors) if pending_errors else None,
                ))
                pending_id = None
                pending_fields = {}
                pending_errors = []
                continue

            # Other AUTOMATION_SIM_ field rows inside a block
            field_m = _FIELD_RE.match(line)
            if field_m is None:
                if pending_id is not None:
                    pending_errors.append(f'malformed AUTOMATION_SIM record: {line!r}')
                continue

            kind = field_m.group(1)
            rest = field_m.group(2)
            parts = rest.split('|')

            # First part is the embedded attack id
            try:
                row_id = int(parts[0])
            except (ValueError, IndexError):
                pending_errors.append(f'parse error: malformed row: {line!r}')
                continue

            if row_id != pending_id:
                pending_errors.append(
                    f'id mismatch in {kind} row: block={pending_id} row={row_id}')
                continue

            # UNSUPPORTED rows signal hidden state; quarantine the whole block.
            if kind == 'UNSUPPORTED':
                reason = '|'.join(parts[1:]) if len(parts) > 1 else 'unknown'
                pending_errors.append(f'unsupported state: {reason}')
                continue

            # Build a canonical key that excludes the value so conflicts are detectable.
            # CREATURE: parts = [id, owner, field, value]      → key=(CREATURE, owner, field)
            # ATTACK:   parts = [id, owner, atk_key, field, value] → key=(ATTACK, owner, atk_key, field)
            # EFFECT:   parts = [id, owner, eff_key, field, value] → key=(EFFECT, owner, eff_key, field)
            # Others:   all dimension parts form the key, last part is the value.
            if len(parts) < 3:
                pending_errors.append(f'parse error: too few parts in {kind} row: {line!r}')
                continue

            value = parts[-1]
            # key = (kind, *dimension_parts_excluding_value)
            canonical_key = (kind,) + tuple(parts[1:-1])

            if canonical_key in pending_fields:
                existing = pending_fields[canonical_key]
                if existing != value:
                    pending_errors.append(
                        f'conflicting values for {canonical_key}: '
                        f'{existing!r} vs {value!r}')
                # Exact duplicate (same value): silently skip.
            else:
                pending_fields[canonical_key] = value

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
