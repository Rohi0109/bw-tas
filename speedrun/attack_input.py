"""Native selection and submission handshake. Timing/guards are intentionally unchanged."""

from __future__ import annotations

import time
from pathlib import Path

from x11_controller import X11Keyboard
from runner_logging import log_message
from runner_telemetry import (SELECTION_RE, ATTACK_SUBMITTED_RE, DIALOG_ACTIVE_RE,
                              DIALOG_INACTIVE_RE, ATTACK_READY_RE, INCAP_OVERLAY_RE,
                              POWERUP_STATE_RE)


def select_and_attack_when_native_ready(
    controller: X11Keyboard, log_path: Path, board: str, word: str,
    delay: float, path: tuple[int, ...] | None, timeout: float = 1.0,
    allow_presentation_skip: bool = True,
    confirm_each_tile: bool = False,
) -> bool:
    """Click Attack only after Deluxe owns the complete intended selection."""
    controller.last_attack_ready_latency_ms = float("inf")
    if log_path.exists():
        existing = list(SELECTION_RE.finditer(
            log_path.read_text(encoding="utf-8", errors="replace")[-8192:]
        ))
        if existing and int(existing[-1].group("count")) != 0:
            clear_start = log_path.stat().st_size
            controller.clear_selection(delay)
            time.sleep(delay)
            if confirm_each_tile:
                clear_deadline = time.monotonic() + 0.3
                while True:
                    with log_path.open("r", encoding="utf-8", errors="replace") as events:
                        events.seek(clear_start)
                        cleared = list(SELECTION_RE.finditer(events.read()))
                    if cleared and int(cleared[-1].group("count")) == 0:
                        break
                    if time.monotonic() >= clear_deadline:
                        return False
                    time.sleep(0.005)
    start = log_path.stat().st_size if log_path.exists() else 0
    def confirm_tile(expected_count: int) -> bool:
        deadline = time.monotonic() + 0.15
        while time.monotonic() < deadline:
            with log_path.open("r", encoding="utf-8", errors="replace") as events:
                events.seek(start)
                matches = list(SELECTION_RE.finditer(events.read()))
            if matches and int(matches[-1].group("count")) == expected_count:
                return True
            time.sleep(0.005)
        return False

    selection_started_at = time.monotonic()
    selection_result = controller.select_word(
        board, word, delay, path, clear_first=False,
        confirm_tile=confirm_tile if confirm_each_tile else None,
    )
    if selection_result is False:
        return False
    selection_returned_at = time.monotonic()
    final_tile_at = getattr(controller, "last_tile_click_sent_at", None)
    if final_tile_at is not None:
        log_message(
            f"Attack timing {word.upper()}: selection_ms="
            f"{(selection_returned_at - selection_started_at) * 1000:.1f}; "
            f"final_tile_return_ms="
            f"{(selection_returned_at - final_tile_at) * 1000:.1f}"
        )
    deadline = time.monotonic() + timeout
    selection_presentation_active = False
    native_selection_complete = False
    presentation_deadline = None
    presentation_skip_attempts = 0
    with log_path.open("r", encoding="utf-8", errors="replace") as log:
        log.seek(start)
        while time.monotonic() < deadline:
            text = log.read()
            # Enter can submit the word directly from the valid-word
            # presentation without producing a separate ATTACK_READY edge.
            # Treat that native acknowledgement as success immediately;
            # otherwise a completed attack needlessly waits out this helper's
            # full timeout before the combat loop can observe the result.
            if ATTACK_SUBMITTED_RE.search(text) or "User clicked ATTACK" in text:
                acknowledged_at = time.monotonic()
                log_message(
                    f"Attack timing {word.upper()}: submitted during "
                    "presentation skip; final_tile_to_ack_ms="
                    f"{((acknowledged_at - final_tile_at) * 1000):.1f}"
                    if final_tile_at is not None
                    else f"Attack timing {word.upper()}: submitted during "
                    "presentation skip."
                )
                return True
            selection_matches = list(SELECTION_RE.finditer(text))
            if selection_matches:
                latest_selection = selection_matches[-1]
                native_selection_complete = (
                    int(latest_selection.group("count")) == len(path or word)
                    and latest_selection.group("valid") == "1"
                )
            presentation_events = []
            presentation_events.extend(
                (match.start(), match.group("source") == "interrupt")
                for match in DIALOG_ACTIVE_RE.finditer(text)
            )
            presentation_events.extend(
                (match.start(), False)
                for match in DIALOG_INACTIVE_RE.finditer(text)
            )
            for _, selection_presentation_active in sorted(presentation_events):
                pass
            if native_selection_complete and selection_presentation_active and presentation_deadline is None:
                # Long native presentations outlive the ordinary selection
                # timeout. Keep this selection owned, with one bounded extension.
                presentation_deadline = time.monotonic() + 8.0
                deadline = max(deadline, presentation_deadline)
            if (
                selection_presentation_active
                and native_selection_complete
                and allow_presentation_skip
                and presentation_skip_attempts < 40
            ):
                presentation_skip_attempts += 1
                if presentation_skip_attempts == 1:
                    log_message(
                        f"Attack timing {word.upper()}: valid-word presentation "
                        "active; starting bounded 10 ms Enter skip."
                    )
                controller.click_attack(min(delay, 0.01))
            matches = list(ATTACK_READY_RE.finditer(text))
            if matches:
                latest = matches[-1]
                if int(latest.group("count")) == len(path or word):
                    ready_received_at = time.monotonic()
                    final_to_ready = (
                        (ready_received_at - final_tile_at) * 1000
                        if final_tile_at is not None else -1
                    )
                    log_message(
                        f"Attack timing {word.upper()}: ready_received; "
                        f"final_tile_to_ready_ms={final_to_ready:.1f}; "
                        f"presentation_skip_attempts={presentation_skip_attempts}"
                    )
                    controller.last_attack_ready_latency_ms = final_to_ready
                    early_ready = 0 <= final_to_ready < 250
                    input_delay = min(delay, 0.01) if early_ready else delay
                    input_attempt = 0
                    input_result = "pending"
                    while input_attempt < 40:
                        input_attempt += 1
                        controller.click_attack(input_delay)
                        response = log.read()
                        if ATTACK_SUBMITTED_RE.search(response) or (
                            "User clicked ATTACK" in response
                        ):
                            input_result = "acknowledged"
                            break
                        if DIALOG_ACTIVE_RE.search(response):
                            input_result = "interrupt"
                            break
                        # A normal post-presentation readiness edge needs only
                        # one input; the burst exists solely to cross the brief
                        # false-idle window exposed immediately after selection.
                        if not early_ready:
                            break
                    enter_at = getattr(
                        controller, "last_attack_key_sent_at", ready_received_at
                    )
                    log_message(
                        f"Attack timing {word.upper()}: enter_sent; "
                        f"ready_to_enter_ms={(enter_at - ready_received_at) * 1000:.1f}; "
                        f"attempts={input_attempt}; result={input_result}"
                    )
                    return True
            # This helper owns a complete valid rack. Generic safe-point
            # dialogue clicks are intentionally excluded: Enter above can only
            # advance this selection's presentation and cannot touch a tile.
            if INCAP_OVERLAY_RE.search(text):
                return False
            time.sleep(0.01)
    if native_selection_complete:
        raise RuntimeError(
            f"Confirmed selection {word.upper()} did not release within its bounded "
            "presentation wait; preserving the rack instead of clearing/retyping"
        )
    return False


def activate_powerup_when_native_ready(
    controller: X11Keyboard, log_path: Path, delay: float,
    timeout: float = 8.0, retry_after: float = 2.0,
) -> bool:
    """Use Power-Up and wait until its native effect yields input ownership.

    A potion click can be rejected during the short encounter handoff even
    though the new board is already visible. Retry the same inventory slot
    once, but only while native telemetry still proves that the effect is not
    active. Never re-click after activation: the remaining wait may represent
    a real overlay that still owns input.
    """
    controller.clear_selection(delay)
    start = log_path.stat().st_size if log_path.exists() else 0
    controller.use_powerup_potion(max(0.8, delay))
    started_at = time.monotonic()
    deadline = started_at + timeout
    retry_at = started_at + min(retry_after, max(0.0, timeout / 2))
    retried = False
    latest = None
    with log_path.open("r", encoding="utf-8", errors="replace") as log:
        log.seek(start)
        telemetry = ""
        while time.monotonic() < deadline:
            # Wine can expose an appended console record across multiple
            # reads. Preserve the unfinished tail instead of discarding it.
            telemetry = (telemetry + log.read())[-4096:]
            matches = list(POWERUP_STATE_RE.finditer(telemetry))
            if matches:
                latest = matches[-1]
                if (
                    latest.group("active") == "1"
                    and latest.group("input_ready") == "1"
                ):
                    return True
            if (
                not retried and time.monotonic() >= retry_at
                and (latest is None or latest.group("active") == "0")
            ):
                log_message(
                    "Power-Up is still natively inactive; retrying its item "
                    "click once.", flush=True,
                )
                controller.use_powerup_potion(max(0.8, delay))
                retried = True
            time.sleep(0.01)
    if latest is None:
        detail = "no native Power-Up telemetry observed"
    else:
        blocker = latest.group("blocker") or "unspecified"
        detail = (
            f"active={latest.group('active')}; "
            f"input_ready={latest.group('input_ready')}; blocker={blocker}"
        )
    log_message(f"Power-Up native confirmation timed out: {detail}.", flush=True)
    return False

