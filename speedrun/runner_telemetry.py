"""Lua event grammar and log recovery. Never chooses words or sends input."""

from __future__ import annotations

import re
from pathlib import Path

from combat_models import DeluxeState
from combat_telemetry import READY_SEQ_RE


BOARD_PREFIX = "AUTOMATION_BOARD="
READY_PREFIX = "AUTOMATION_READY="
BOARD_EVENT_RE = re.compile(
    r"AUTOMATION_(?P<kind>BOARD|READY)="
    r"(?P<board>[A-Z]{4}/[A-Z]{4}/[A-Z]{4}/[A-Z]{4})"
)
DONE_MARKER = "no more enemies left"
CHAPTER_RE = re.compile(
    r"Book:StartGame called for book (?P<book>[^,]+), chapter (?P<chapter>\d+)"
)
DIALOG_ACTIVE_RE = re.compile(
    r"AUTOMATION_DIALOG_ACTIVE=(?P<source>[a-z]+)\|(?P<sequence>\d+)\|E"
)
DIALOG_PULSE_RE = re.compile(
    r"AUTOMATION_DIALOG_PULSE=(?P<source>[a-z]+)\|(?P<sequence>\d+)\|"
    r"(?P<pulse>\d+)\|E"
)
DIALOG_INACTIVE_RE = re.compile(r"AUTOMATION_DIALOG_INACTIVE=(?P<sequence>\d+)\|E")
PLAY_TUTORIAL_RE = re.compile(r"AUTOMATION_PLAY_TUTORIAL=(?P<sequence>\d+)\|E")
PLAY_READY_RE = re.compile(
    r"AUTOMATION_PLAY_READY=(?P<letter>P|L|A|Y|DONE)\|(?P<pulse>\d+)\|E"
)
LEGACY_SCREEN_RE = re.compile(
    r"AUTOMATION_DIALOG=(?P<kind>treasure|none)\|(?P<sequence>\d+)\|E"
)
DEFEATED_RE = re.compile(r"AUTOMATION_DEFEATED=(?P<enemy>[^|]+)\|E")
ZERO_HEALTH_RE = re.compile(r"AUTOMATION_ZERO_HEALTH=(?P<enemy>[^|]+)\|E")
DEATH_FLAGS_RE = re.compile(
    r"AUTOMATION_DEATH_FLAGS=(?P<enemy>[^|]+)\|"
    r"(?P<anims_done>true|false|nil)\|(?P<death_sequence>true|false|nil)\|"
    r"(?P<final_sequence>true|false|nil)\|(?P<interrupt>true|false|nil)\|"
    r"(?P<boss_state>[^|]+)\|(?P<checkpoint_state>[^|]+)\|E"
)
ATTACK_SUBMITTED_RE = re.compile(
    r"AUTOMATION_ATTACK_SUBMITTED=(?P<enemy>[^|]+)\|E"
)
SELECTION_RE = re.compile(
    r"AUTOMATION_SELECTION=(?P<count>\d+)\|(?P<value>-?\d+(?:\.\d+)?)\|"
    r"(?P<valid>[01])\|E"
)
ATTACK_READY_RE = re.compile(
    r"AUTOMATION_ATTACK_READY=(?P<count>\d+)\|"
    r"(?P<value>-?\d+(?:\.\d+)?)\|E"
)
POWERUP_STATE_RE = re.compile(
    r"AUTOMATION_POWERUP_STATE=(?P<active>[01])\|(?P<input_ready>[01])"
    r"(?:\|(?P<blocker>[^|]+))?\|E"
)
RESET_READY_RE = re.compile(
    r"AUTOMATION_BOSS_RESET_READY=(?P<enemy>[^|]+)\|E"
)
PLAYER_STUNNED_RE = re.compile(
    r"AUTOMATION_PLAYER_(?P<kind>STUNNED|FROZEN|PETRIFIED)=(?P<active>[01])"
    r"(?:\|(?P<hp>-?\d+(?:\.\d+)?)\|(?P<max_hp>-?\d+(?:\.\d+)?)"
    r"\|(?P<health_potion>[01])(?:\|(?P<purify_potion>[01]))?)?\|E"
)
INCAP_OVERLAY_RE = re.compile(
    r"AUTOMATION_INCAP_OVERLAY=(?P<kind>stunned|frozen|petrified)\|"
    r"(?P<frame>[^|]+)"
    r"(?:\|(?P<hp>-?\d+(?:\.\d+)?)\|(?P<max_hp>-?\d+(?:\.\d+)?)"
    r"\|(?P<health_potion>[01])\|(?P<purify_potion>[01]))?\|E"
)
CHAPTER_MAP_RE = re.compile(
    r"AUTOMATION_CHAPTER_MAP=(?P<book>nil|\d+)\|"
    r"(?P<current>nil|\d+)\|(?P<chapter>nil|\d+)\|"
    r"(?P<selected>-?\d+)\|(?P<enabled>true|false)\|E"
)
CHAPTER_ACTION_RE = re.compile(
    r"AUTOMATION_CHAPTER_ACTION=(?P<action>[a-z-]+)\|E"
)
LUA_WAIT_MARKER = "Program in waiting. Type go() or press F5 to continue execution."
TREASURE_CONTEXT_RE = re.compile(
    r"AUTOMATION_TREASURE_CONTEXT=(?P<book>nil|\d+)\|"
    r"(?P<current>nil|\d+)\|(?P<selected>-?\d+)\|E"
)
MINIGAME_PROMPT_RE = re.compile(
    r"AUTOMATION_MINIGAME_PROMPT=(?P<book>nil|\d+)\|"
    r"(?P<chapter>-?\d+)\|(?P<sequence>\d+)\|E"
)
def ready_sequence_is_fresh(sequence: int, required_after: int | None) -> bool:
    """Only a later native rack may reclaim input after an overlay."""
    return required_after is None or sequence > required_after


def streamed_ready_sequence(line: str, previous: int) -> int:
    """Advance only from consumed events, never a look-ahead state snapshot."""
    match = READY_SEQ_RE.search(line)
    return max(previous, int(match.group('seq'))) if match else previous


def lua_runtime_is_waiting(text: str) -> bool:
    """Recognize the debugger pause emitted by the embedded Lua runtime."""
    marker_at = text.rfind(LUA_WAIT_MARKER)
    if marker_at < 0:
        return False
    suffix = text[marker_at + len(LUA_WAIT_MARKER):]
    return not suffix.strip("\x00\b >\r\n\t")


def state_is_incapacitated(state: DeluxeState | None) -> bool:
    """Recover an active native overlay when the runner attaches mid-effect."""
    return bool(
        state is not None
        and (state.player_stunned or state.player_frozen or state.player_petrified)
    )


def latest_incapacitation_state(
    text: str, state: DeluxeState | None = None,
) -> bool:
    """Replay post-snapshot incap edges when attaching to an existing log."""
    active = {
        "stunned": bool(state is not None and state.player_stunned),
        "frozen": bool(state is not None and state.player_frozen),
        "petrified": bool(state is not None and state.player_petrified),
    }
    for event in PLAYER_STUNNED_RE.finditer(text):
        active[event.group("kind").casefold()] = event.group("active") == "1"
    return any(active.values())


def latest_active_incapacitation_event(text: str):
    """Return the latest telemetry edge for a status that remains active."""
    active_events = {"stunned": None, "frozen": None, "petrified": None}
    for event in PLAYER_STUNNED_RE.finditer(text):
        kind = event.group("kind").casefold()
        active_events[kind] = event if event.group("active") == "1" else None
    remaining = [event for event in active_events.values() if event is not None]
    return max(remaining, key=lambda event: event.start(), default=None)


def latest_unresolved_incapacitation_overlay(text: str):
    """Recover an overlay frame emitted after the latest actionable READY."""
    overlays = list(INCAP_OVERLAY_RE.finditer(text))
    if not overlays:
        return None
    latest = overlays[-1]
    return latest if latest.start() > text.rfind("AUTOMATION_READY_SEQ=") else None


def latest_unresolved_minigame_prompt(text: str):
    """Return a prompt only while no later native screen proves it resolved."""
    prompts = list(MINIGAME_PROMPT_RE.finditer(text))
    if not prompts:
        return None
    prompt = prompts[-1]
    suffix = text[prompt.end():]
    if any(event.group("action") in {"minigame-callback", "start-game"}
           for event in CHAPTER_ACTION_RE.finditer(suffix)):
        return None
    if TREASURE_CONTEXT_RE.search(suffix) or READY_SEQ_RE.search(suffix):
        return None
    if any(event.group("kind") == "treasure"
           for event in LEGACY_SCREEN_RE.finditer(suffix)):
        return None
    return prompt


def read_log_tail(log_path: Path, offset: int = 0) -> str:
    if not log_path.exists():
        return ""
    with log_path.open("r", encoding="utf-8", errors="replace") as stream:
        stream.seek(offset if log_path.stat().st_size >= offset else 0)
        return stream.read()


def read_seed(log_path: Path, offset: int = 0) -> tuple[str | None, bool, bool, int | None]:
    """Recover only the latest board/combat state, never replay every old turn."""
    board = None
    ready = False
    done = False
    chapter = None
    if not log_path.exists():
        return board, ready, done, chapter
    for line in read_log_tail(log_path, offset).splitlines():
        match = CHAPTER_RE.search(line)
        if match:
            chapter = int(match.group("chapter"))
            # PopCap carries the final board into the next chapter. Keep the
            # latest snapshot when Lua has no reason to emit it again.
            ready = False
            done = False
        for event in BOARD_EVENT_RE.finditer(line):
            board = event.group("board")
            ready = event.group("kind") == "READY"
        if "User clicked ATTACK" in line:
            ready = False
        if DONE_MARKER in line:
            done = True
    return board, ready, done, chapter


def unresolved_play_tutorial(text: str) -> bool:
    """Recognize PLAY when its event predates the runner's tail cursor."""
    plays = list(PLAY_TUTORIAL_RE.finditer(text))
    if not plays:
        return False
    play = plays[-1]
    sequence = int(play.group("sequence"))
    return not any(
        int(match.group("sequence")) == sequence and match.start() > play.start()
        for match in DIALOG_INACTIVE_RE.finditer(text)
    )


def read_latest_dialog(log_path: Path, offset: int = 0) -> str | None:
    """Recover the most recently reported dialogue or non-combat screen."""
    latest = None
    if not log_path.exists():
        return latest
    text = read_log_tail(log_path, offset)
    events = []
    events.extend((m.start(), m.group("source")) for m in DIALOG_ACTIVE_RE.finditer(text))
    events.extend((m.start(), None) for m in DIALOG_INACTIVE_RE.finditer(text))
    events.extend(
        (m.start(), "treasure" if m.group("kind") == "treasure" else None)
        for m in LEGACY_SCREEN_RE.finditer(text)
    )
    for _, latest in sorted(events):
        pass
    return latest


def read_screen_blocker(log_path: Path) -> str | None:
    """Recover a non-combat screen that must suppress fallback clicks."""
    latest = read_latest_dialog(log_path)
    return latest if latest == "treasure" else None
