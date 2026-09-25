"""Continuously solve boards emitted by the Lua automation hook."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

from live_runner import best_word
from x11_controller import X11Keyboard
from combat_models import Candidate, DeluxeState, WordSpec
from combat_telemetry import READY_SEQ_RE, parse_state
from runner_telemetry import (
    latest_unresolved_minigame_prompt,
    BOARD_PREFIX,
    READY_PREFIX,
    BOARD_EVENT_RE,
    DONE_MARKER,
    CHAPTER_RE,
    DIALOG_ACTIVE_RE,
    DIALOG_PULSE_RE,
    DIALOG_INACTIVE_RE,
    PLAY_TUTORIAL_RE,
    PLAY_READY_RE,
    LEGACY_SCREEN_RE,
    DEFEATED_RE,
    ZERO_HEALTH_RE,
    DEATH_FLAGS_RE,
    ATTACK_SUBMITTED_RE,
    SELECTION_RE,
    ATTACK_READY_RE,
    POWERUP_STATE_RE,
    RESET_READY_RE,
    PLAYER_STUNNED_RE,
    INCAP_OVERLAY_RE,
    CHAPTER_MAP_RE,
    CHAPTER_ACTION_RE,
    LUA_WAIT_MARKER,
    TREASURE_CONTEXT_RE,
    MINIGAME_PROMPT_RE,
    ready_sequence_is_fresh,
    streamed_ready_sequence,
    lua_runtime_is_waiting,
    state_is_incapacitated,
    latest_incapacitation_state,
    latest_active_incapacitation_event,
    latest_unresolved_incapacitation_overlay,
    read_log_tail,
    read_seed,
    unresolved_play_tutorial,
    read_latest_dialog,
    read_screen_blocker,
)
from combat_policy import (
    SPHINX_ANSWERS,
    boss_finish_strategy,
    health_potion_confirmed,
    incapacitation_recovery_action,
    is_book3_final_gauntlet,
    should_use_health_potion,
    should_use_powerup_potion,
    should_use_purification_potion,
    sphinx_allows_damage_fallback,
    sphinx_candidate,
)
from attack_lifecycle import AttackLifecycle
from rack_prefetch import RackPrefetch
from deluxe_optimizer import (
    candidates, choose, load_chapter1_hp_map,
    index_words, load_metal_words, strategy_for_state,
    validate_chapter1_state,
)
from book1_optimizer import (
    TELEMETRY_SCHEMA_VERSION, DecisionOverrides, TransitionCorpus, candidate_payload,
    choose_recorded_lookahead, pareto_candidates, state_fingerprint,
    state_payload,
)
from deluxe_route import (
    encounter_key, is_boss_encounter, is_chapter_boss_defeat,
    normalize_enemy, post_victory_reset_reason,
)
from menu_runner import event_driven_reset_timing, reset_from_battle
from run_timer import (
    ENEMY_CHAPTERS, normalize_enemy as normalize_roster_enemy,
    DEFAULT_STATE as DEFAULT_TIMER_STATE,
    load_state as load_timer_state,
    mark_current_issue,
    process_line as process_timer_line,
    save_run_history,
    save_state as save_timer_state,
    update_tas_best,
)


from runner_logging import LOGGER, configure_logging, log_message
from attack_input import select_and_attack_when_native_ready, activate_powerup_when_native_ready


RESET_MENU_TIMING = event_driven_reset_timing()
MENU_REENTRY_RETRY_SECONDS = 0.20


def chapter_map_confirms_menu_reentry(enabled: bool) -> bool:
    """Any consumed native map event ends main-menu input ownership.

    CanClickContinue describes the Enter button, not whether Adventure worked.
    A disabled/animating map still must never receive Adventure coordinates.
    """
    return True


def acquire_runner_lock(lock_path: Path):
    """Hold an exclusive process lock before creating an input controller."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        raise RuntimeError(
            "another TAS runner is already active; refusing duplicate input"
        )
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(f"{os.getpid()}\n")
    lock_file.flush()
    return lock_file


SPHINX_ANSWERS = {
    "Sphinx (Riddle 1 of 5)": "SKY",
    "Sphinx (Riddle 2 of 5)": "WALL",
    "Sphinx (Riddle 3 of 5)": "FIST",
    "Sphinx (Riddle 4 of 5)": "TRUTH",
    "Sphinx (Last Riddle)": "WATER",
}
TUTORIAL_PLAY_BOARD = "SFAE/PFUN/RJDY/TLIS"
TREASURE_LOADOUT_AFTER_BOSS = {
    "Circe (Boss)": (0, 2, 3),       # Bow, Golden Fleece, Icarus Sandals
    "Cerberus (Boss)": (0, 3, 6),    # Bow, Icarus Sandals, Heph's Hammer
    "Minotaur (Boss)": (0, 3, 6),    # Bow, Boots of Theseus, Heph's Hammer
    "Hydra (Boss)": (0, 3, 6),       # Arch, Boots, Wooden Parrot upgrades
    "Maladin (Boss)": (0, 6, 18),    # Arch, Hand, Wooden Parrot
}

PURIFY_AFTER_HIT_ENEMIES = frozenset({
    "Lesser Basilisk", "Greater Basilisk", "Medusa (Boss)",
})


def treasure_slots_after(enemy: str) -> tuple[int, ...] | None:
    """Resolve multi-phase boss display names to their treasure route."""
    route_enemy = "Hydra (Boss)" if enemy.startswith("Hydra (Head ") else enemy
    return TREASURE_LOADOUT_AFTER_BOSS.get(route_enemy)


def clear_stale_treasure_transition(
    source: str, blocked_screen: str | None, selection_started: bool,
) -> tuple[str | None, bool]:
    """Let a native conversation supersede a stale treasure-screen marker.

    Deluxe can publish its legacy treasure edge before the post-boss Cassandra
    conversation becomes active. Once ``convpanel.Active()`` is true, the
    visible screen is authoritatively a conversation and treasure clicks must
    no longer suppress its Lua-authorized pulses.
    """
    if source == "convpanel":
        return None, False
    return blocked_screen, selection_started


def convpanel_supersedes_navigation_transition(source: str) -> bool:
    """A live conversation proves menu/map navigation has completed.

    Chapter startup can expose its conversation before the first BOARD/READY
    snapshot that normally clears navigation retries. The conversation itself
    is then the authoritative MouseUp owner and must not be suppressed.
    """
    return source == "convpanel"


def post_treasure_convpanel_supersedes_boss_reset(
    source: str, blocked_screen: str | None, treasure_selection_started: bool,
) -> bool:
    """A post-treasure conversation proves the prior boss reset is complete."""
    return source == "convpanel" and (
        blocked_screen == "treasure" or treasure_selection_started
    )


def clear_stale_treasure_on_ready(
    blocked_screen: str | None, selection_started: bool,
) -> tuple[str | None, bool]:
    """Treat native combat READY as proof the treasure transition is over."""
    return None, False


def telemetry_context(
    state: DeluxeState, timer_state: dict | None,
) -> tuple[int, int]:
    """Recover the chapter omitted by Deluxe and freeze it at submission.

    Most native Deluxe snapshots report chapter ``-1``. The persistent timer
    has already resolved the chapter from the enemy roster, and must be read
    when input is submitted (not when the next enemy arrives).
    """
    if state.book >= 1 and state.chapter >= 1:
        return state.book, state.chapter
    current = timer_state.get("current") if timer_state is not None else None
    if current is not None:
        return int(current["book"]), int(current["chapter"])
    return state.book, ENEMY_CHAPTERS.get(
        (state.book, normalize_roster_enemy(state.enemy)), state.chapter,
    )


def treasure_slots_for_state(state: DeluxeState) -> tuple[int, ...] | None:
    """Choose the route loadout for a treasure screen after this state."""
    slots = treasure_slots_after(state.enemy)
    if slots is not None:
        return slots
    if state.book == 1:
        # A loadout room can also appear after a non-boss checkpoint. Preserve
        # the already validated Book 1 route instead of waiting for a boss name.
        if "heph's hammer" in state.treasures:
            return (0, 3, 6)
        if "icarus sandals" in state.treasures:
            return (0, 2, 3)
    if (
        state.book == 2 and state.chapter == 4
        and state.enemy.casefold().startswith("sphinx")
        and "jeweled key" in state.treasures
    ):
        # Reloading directly into Sphinx can preserve Key as selection 1/3.
        # Toggle its fixed grid position off before choosing the route.
        return (11, 0, 1, 2)
    if state.book == 3:
        # Book 3 repeatedly asks for a loadout at chapter entry. Keep the
        # validated Arch of Xyzzy + Hand of Hercules + Wooden Parrot route even
        # when the chapter-map transition has replaced the submitted boss.
        return (0, 6, 18)
    return None


def treasure_slots_for_context(book: int, selected_chapter: int) -> tuple[int, ...] | None:
    """Recover the validated loadout when the runner starts in Treasure Room."""
    if book == 1:
        if selected_chapter == 5:
            return (0, 2, 3)  # Bow, Golden Fleece, Icarus Sandals
        if selected_chapter >= 6:
            return (0, 3, 6)  # chapter-appropriate Bow/Arch, Boots, Hammer/Parrot
    if book == 2:
        if selected_chapter == 4:
            return (0, 1, 2)  # Arch, Aegis, Golden Fleece
        if selected_chapter > 5:
            return (0, 6, 18)  # Arch, Hand of Hercules, Wooden Parrot
        return (0, 3, 6)
    if book == 3:
        return (0, 6, 18)     # Arch, Hand of Hercules, Wooden Parrot
    return None


def should_confirm_book_movie_skip(
    state: DeluxeState | None, probe_count: int,
    chapter_override: int | None = None,
) -> bool:
    """Recognize the uninstrumented movie-skip confirmation between books."""
    return (
        state is not None
        and (
            state.chapter == 10
            or (state.chapter < 1 and chapter_override == 10)
        )
        and is_boss_encounter(state)
        and probe_count >= 20
    )


def immediate_defeated_reset_reason(
    state: DeluxeState | None,
    defeated_enemy: str,
    already_reset: set[tuple[int, int, int, str]],
    chapter_override: int | None,
) -> str | None:
    """Return a route reset only after Lua confirms the defeat was committed."""
    if state is None or state.enemy != defeated_enemy:
        return None
    # Chapter bosses publish DEFEATED only after the following chapter has
    # started. Resetting at that late edge interrupts the new chapter rather
    # than skipping the completed encounter.
    if is_chapter_boss_defeat(state):
        return None
    return post_victory_reset_reason(state, already_reset, chapter_override)


def attack_state_for_event(
    submitted: DeluxeState | None, last_attack: DeluxeState | None,
    enemy: str,
) -> DeluxeState | None:
    """Keep route identity after an overlay cancels only pending rack input."""
    for state in (submitted, last_attack):
        if state is not None and state.enemy == enemy:
            return state
    return None


def should_arm_boss_reset_on_zero_health(
    state: DeluxeState | None,
) -> bool:
    """Arm the earliest recoverable main-menu exit after a real boss kill.

    RESET_READY is the first point where the native death animation has settled
    and the battle menu can safely own input. If quitting beats the save commit,
    the existing full-health replay check clears the guard and reruns the boss.
    Codex ends the run directly; Hydra's intermediate heads and Sphinx rounds
    are continuous encounters and must not leave through the menu. Mummy and
    Dracula use normal chapter completion until main-menu ownership can be
    positively verified: Adventure coordinates can select Moxie on their maps.
    """
    if state is None:
        return False
    normalized = normalize_enemy(state.enemy)
    sphinx_complete = normalized == "sphinxlastriddle"
    if not is_boss_encounter(state) and not sphinx_complete:
        return False
    return not (
        normalized in {"codex", "codexfinalboss", "themummyboss", "draculaboss"}
        or normalized.startswith("hydrahead")
        or (normalized.startswith("sphinx") and not sphinx_complete)
    )


def boss_replay_is_fresh(state: DeluxeState, reset_sequence: int | None) -> bool:
    """A cached pre-kill full-health READY is not evidence of a replay."""
    return (reset_sequence is not None and state.sequence > reset_sequence
            and state.hp >= state.max_hp > 0)


def enemy_accepts_candidate(state: DeluxeState, candidate: Candidate) -> bool:
    """Apply known enemy word immunities before strategy ranking."""
    enemy = state.enemy.casefold()
    if enemy.startswith((
        "mama roc", "medusa", "angry mob", "nemean lion", "the mummy",
        "mirage xel", "fallen wizard hero",
    )):
        return len(candidate.word) > 3
    return True


def refresh_rejected_words_context(
    rejected_words: set[str],
    previous_context: tuple[str, str] | None,
    state: DeluxeState,
) -> tuple[str, str]:
    """Keep input-failure exclusions local to one enemy rack."""
    context = (state.enemy, state.board)
    if context != previous_context:
        rejected_words.clear()
    return context


def tile_input_delay(state: DeluxeState | None, configured_delay: float) -> float:
    """Pace racks with known unusually late native input handoffs.

    Re-clicking an apparently unconfirmed tile is unsafe: telemetry can lag an
    accepted click, and the retry then deselects it. The fresh READY sequence
    already proves rack ownership, so use one deliberately paced click per
    tile instead.
    """
    if state is not None and (
        (state.book == 1 and state.chapter == 6 and state.enemy == "Griffon")
        or state.enemy == "Hydra (Main Head)"
    ):
        return max(configured_delay, 0.08)
    if state is not None and (
        state.book == 1 and state.chapter == 1 and state.enemy == "War Hound"
    ):
        # The first post-tutorial start-game snapshot can precede the rack's
        # stable MouseUp handoff by a frame. Ten-millisecond clicks have been
        # observed to vanish here; the retry's 20 ms cadence is reliable.
        return max(configured_delay, 0.02)
    return configured_delay


def is_initial_play_tutorial(
    board: str | None, active_dialog: str | None, state: DeluxeState | None,
    attacks: int,
) -> bool:
    """Recognize Deluxe's fixed PLAY lesson despite a stale launch snapshot."""
    return (
        board == TUTORIAL_PLAY_BOARD
        and active_dialog == "interrupt"
    )


def dialogue_pulse_suppressed(
    boss_reset_pending: bool, treasure_active: bool,
    chapter_transition: bool, menu_transition: bool,
    selection_pending: bool = False,
) -> bool:
    """Protect non-dialogue screens from otherwise valid Lua pulses."""
    return (
        boss_reset_pending or treasure_active
        or chapter_transition or menu_transition or selection_pending
    )


def clear_special_transitions_on_chapter_start(
    action: str, boss_reset_state: DeluxeState | None,
    blocked_screen: str | None, treasure_selection_started: bool,
) -> tuple[DeluxeState | None, str | None, bool]:
    """A native start-game action proves every prior transition is finished."""
    if action == "start-game":
        return None, None, False
    return boss_reset_state, blocked_screen, treasure_selection_started


def boss_reset_dialog_recovery_allowed(
    source: str, menu_reentry_pending: bool,
    last_boss_reset_key: tuple[int, int, int, str] | None,
) -> bool:
    """Allow only a post-reset result overlay to unblock a missed menu exit."""
    return bool(
        menu_reentry_pending
        and last_boss_reset_key is not None
        and source in {"interrupt", "convpanel", "levelup"}
    )


def book_transition_dialog_click_required(
    last_boss_reset_key: tuple[int, int, int, str] | None,
    completed_clicks: int,
) -> bool:
    """Clear the two uninstrumented Lex panels after finishing Book 1."""
    return bool(
        last_boss_reset_key is not None
        and last_boss_reset_key[0] == 1
        and normalize_enemy(last_boss_reset_key[3]).removesuffix("boss") == "medusa"
        and completed_clicks < 2
    )


def should_retry_minigame_prompt(
    pending_sequence: int | None, attempts: int,
    now: float, retry_at: float,
) -> bool:
    """Retry an unconfirmed Moxie Yes click with a bounded budget."""
    return pending_sequence is not None and attempts < 5 and now >= retry_at


def is_unchanged_combat_snapshot(
    current: DeluxeState, submitted: DeluxeState | None
) -> bool:
    """Reject only sequence churn with no combat-relevant state change.

    Enemy HP and board letters can remain unchanged while an enemy attack
    lowers Lex's health or damages tiles. Those snapshots must be processed so
    healing and damage selection use the new state.
    """
    return bool(
        submitted is not None
        and current == replace(submitted, sequence=current.sequence)
    )


def completes_early_ready(state: DeluxeState, early_ready_board: str | None) -> bool:
    """Recognize the completed snapshot belonging to a previously early READY."""
    return early_ready_board is not None and state.board == early_ready_board


@dataclass
class PreparedSession:
    """Everything loaded before following native events; no hidden local handoff."""

    args: argparse.Namespace
    log_path: Path
    deluxe_words: list[WordSpec]
    metal_words: frozenset[str]
    chapter1_hp: dict
    transition_corpus: TransitionCorpus
    decision_overrides: DecisionOverrides
    controller: X11Keyboard
    run_log_offset: int
    timer_state: dict | None
    telemetry_run_id: str | None


def prepare_game(args: argparse.Namespace) -> PreparedSession:
    """Preload solving resources, attach input, and optionally start a fresh profile."""
    log_path = args.log.resolve()
    # All expensive immutable loading happens before profile confirmation and
    # its timing edge. The same lock/process owns setup and the entire run.
    deluxe_words = []
    metal_words = frozenset()
    chapter1_hp = {}
    if args.layout == "deluxe":
        root = Path(__file__).resolve().parent
        deluxe_words = index_words(list(json.loads(
            (root / "word_dict.json").read_text(encoding="utf-8")
        )))
        metal_words = load_metal_words(
            root.parent / "runtime/deluxe-modded/.tas-data/metals.luc"
        )
        chapter1_hp = load_chapter1_hp_map()
        if args.telemetry is None:
            args.telemetry = root.parent / "runtime/deluxe-modded/tas-timing.jsonl"
        if args.book1_corpus is None:
            args.book1_corpus = args.telemetry
        transition_corpus = TransitionCorpus.load(args.book1_corpus)
    else:
        transition_corpus = TransitionCorpus()
    decision_overrides = DecisionOverrides.load(args.book1_overrides)
    controller = X11Keyboard(args.title, args.layout)
    run_log_offset = 0
    if args.new_run:
        from new_run import last_user, recreate_profile
        log_message("Solver preloaded; recreating the TAS profile. Timer still starts on name confirmation.", flush=True)
        run_log_offset = recreate_profile(
            controller, args.profile or last_user(),
            from_select_user=args.from_select_user, timer_path=args.timer_state,
            startup_bridge=False, log_path=log_path,
        )
    timer_state = None
    if args.timer_state is not None and args.timer_state.exists():
        timer_state = load_timer_state(args.timer_state)
        log_message(f"Chapter timing enabled: {args.timer_state}", flush=True)
    telemetry_run_id = timer_state.get("started_at_iso") if timer_state else None
    if args.experiment:
        from experiment_session import create_session
        telemetry_run_id = create_session(log_path.parent)
        log_message(f"Experiment session: {telemetry_run_id}; race records disabled.", flush=True)
    return PreparedSession(
        args=args,
        log_path=log_path,
        deluxe_words=deluxe_words,
        metal_words=metal_words,
        chapter1_hp=chapter1_hp,
        transition_corpus=transition_corpus,
        decision_overrides=decision_overrides,
        controller=controller,
        run_log_offset=run_log_offset,
        timer_state=timer_state,
        telemetry_run_id=telemetry_run_id,
    )


def follow_game_until_finished(session: PreparedSession) -> None:
    """Own the optional diagnostic handler for exactly one runner session."""
    from menu_trace import MenuTrace
    path = getattr(session.args, 'menu_reset_trace', None)
    trace = MenuTrace(path, session.telemetry_run_id) if path else None
    if trace:
        LOGGER.addHandler(trace)
    try:
        _follow_game_until_finished(session, trace)
    finally:
        if trace:
            LOGGER.removeHandler(trace)
            trace.close()


def _follow_game_until_finished(session: PreparedSession, menu_trace=None) -> None:
    """Follow native events while preserving input ownership and acknowledgement guards."""
    args = session.args
    log_path = session.log_path
    deluxe_words = session.deluxe_words
    metal_words = session.metal_words
    chapter1_hp = session.chapter1_hp
    transition_corpus = session.transition_corpus
    decision_overrides = session.decision_overrides
    controller = session.controller
    run_log_offset = session.run_log_offset
    timer_state = session.timer_state
    telemetry_run_id = session.telemetry_run_id
    board, ready, done, chapter = read_seed(log_path, run_log_offset)
    latest_dialog = read_latest_dialog(log_path, run_log_offset)
    blocked_screen = latest_dialog if latest_dialog == "treasure" else None
    treasure_selection_started = False
    if ready and blocked_screen == "treasure":
        blocked_screen, treasure_selection_started = (
            clear_stale_treasure_on_ready(blocked_screen, False)
        )
        latest_dialog = None
        log_message(
            "Startup combat READY superseded stale treasure transition.",
            flush=True,
        )
    active_dialog = (
        latest_dialog if latest_dialog in {"conversation", "levelup"} else None
    )
    deluxe_state = None
    initial_log_text = ""
    initial_log_size = 0
    if args.layout == "deluxe" and log_path.exists():
        with log_path.open("r", encoding="utf-8", errors="replace") as startup_log:
            startup_log.seek(run_log_offset if log_path.stat().st_size >= run_log_offset else 0)
            initial_log_text = startup_log.read()
            initial_log_size = startup_log.tell()
        # Keep the byte boundary represented by the startup snapshot. Startup
        # recovery clicks can synchronously append status-clear telemetry before
        # the follower opens the log. Seeking to the then-current EOF would skip
        # that confirmation and leave the runner in a stale incapacitated state.
        deluxe_state = parse_state(initial_log_text)
    if done:
        label = f"Chapter {chapter}" if chapter is not None else "Current chapter"
        log_message(f"{label} is already complete.", flush=True)
        return

    attack = AttackLifecycle()
    last_attack_state: DeluxeState | None = None
    required_ready_after_overlay = None
    native_attack_events = []
    tutorial_play_submitted = False
    tutorial_interrupt_active = False
    last_play_letter_clicked: str | None = None
    reset_encounters: set[tuple[int, int, int, str]] = set()
    movie_skip_confirmed: set[tuple[int, int, int, str]] = set()
    map_enter_encounters: set[tuple[int, int, int, str]] = set()
    rejected_words: set[str] = set()
    rejected_words_context: tuple[str, str] | None = None
    dialog_probe_at = (
        time.monotonic() + args.dialog_stall_delay
        if args.layout == "deluxe" and not ready and blocked_screen is None
        else float("inf")
    )
    dialog_probe_count = 0
    chapter_enter_at = float("inf")
    chapter_enter_pending = False
    chapter_enter_attempts = 0
    menu_reentry_at = float("inf")
    menu_reentry_pending = False
    menu_reentry_attempts = 0
    menu_reentry_dialog_clicks = 0
    menu_reset_dialog_seen = False
    boss_reset_state: DeluxeState | None = None
    boss_reset_dialog_ready = False
    pending_health_potion_state: DeluxeState | None = None
    pending_health_potion_at = float("inf")
    pending_health_potion_attempts = 0
    player_incapacitated = latest_incapacitation_state(
        initial_log_text, deluxe_state,
    )
    incap_overlay_retry_at = (
        time.monotonic() if player_incapacitated else float("inf")
    )
    incap_purify_pending = False
    incap_purify_attempts = 0
    incap_purify_failed = False
    incap_health_submitted = False
    startup_overlay = latest_unresolved_incapacitation_overlay(initial_log_text)
    if player_incapacitated:
        startup_incap = latest_active_incapacitation_event(initial_log_text)
        startup_recovery = "continue"
        if startup_incap is not None and startup_incap.group("hp") is not None:
            startup_recovery = incapacitation_recovery_action(
                purify_available=startup_incap.group("purify_potion") == "1",
                health_available=startup_incap.group("health_potion") == "1",
                player_hp=float(startup_incap.group("hp")),
                player_max_hp=float(startup_incap.group("max_hp")),
            )
        if startup_recovery == "purify":
            log_message(
                "Startup incapacitation telemetry confirms Purify is "
                "available; cancelling the lost-turn status.",
                flush=True,
            )
            controller.use_purification_potion(max(0.8, args.delay))
            incap_purify_pending = True
            incap_purify_attempts = 1
            incap_overlay_retry_at = time.monotonic() + 1.0
        elif startup_recovery == "heal_then_continue":
            log_message(
                "Startup incapacitation telemetry confirms low health and no "
                "Purify; healing before accepting the lost turn.",
                flush=True,
            )
            controller.use_health_potion(max(0.8, args.delay))
            incap_health_submitted = True
            incap_overlay_retry_at = time.monotonic() + 1.0
        else:
            log_message(
                "Startup snapshot reports an active incapacitation; "
                "resuming native overlay continuation clicks.",
                flush=True,
            )
    elif startup_overlay is not None:
        # The native status predicate clears before the final petrify/freeze
        # card disappears. Recover that last visible continuation separately
        # instead of mistaking the cleared predicate for actionable combat.
        log_message(
            "Startup log contains an unresolved native "
            f"{startup_overlay.group('kind')} overlay "
            f"(frame {startup_overlay.group('frame')}); clicking its final "
            "continuation area.",
            flush=True,
        )
        controller.dismiss_incapacitation_overlay(args.delay)
    last_boss_reset_key: tuple[int, int, int, str] | None = None
    last_boss_reset_sequence: int | None = None
    treasure_selection_started = False
    handled_minigame_prompts: set[int] = set()
    pending_minigame_prompt: int | None = None
    minigame_prompt_attempts = 0
    minigame_prompt_retry_at = float("inf")
    attacks = 0
    scrambles = 0
    deadline = time.monotonic() + args.timeout
    ready_at = time.monotonic() + args.ready_delay if ready else float("inf")
    early_ready_board: str | None = None

    # Open after seeding and seek to EOF: old boards establish current state but
    # are not replayed as a sequence.
    state_buffer = ""
    rack_prefetch = RackPrefetch()
    stream_ready_sequence = deluxe_state.sequence if deluxe_state is not None else -1
    with log_path.open("r", encoding="utf-8", errors="replace") as log:
        # Replay anything appended after the startup snapshot, including native
        # confirmation produced by a startup Purify click.
        log.seek(initial_log_size if args.layout == "deluxe" else 0, os.SEEK_SET)
        if args.layout != "deluxe":
            log.seek(0, os.SEEK_END)
        # Close the seed-to-tail race: a non-combat event can arrive after
        # read_seed() but before this cursor is established.
        startup_text = read_log_tail(log_path, run_log_offset)
        if lua_runtime_is_waiting(startup_text):
            log_message("Recovering paused Lua runtime with F5.", flush=True)
            controller.resume_lua_runtime(args.delay)
            deadline = time.monotonic() + args.timeout
        _, refreshed_ready, _, _ = read_seed(log_path, run_log_offset)
        refreshed_dialog = read_latest_dialog(log_path, run_log_offset)
        if (
            refreshed_dialog == "interrupt"
            and unresolved_play_tutorial(startup_text)
            and not tutorial_play_submitted
        ):
            tutorial_play_submitted = True
            tutorial_interrupt_active = True
            active_dialog = "interrupt"
            log_message(
                "Recovering fixed fresh-profile PLAY tutorial from active "
                "startup marker.",
                flush=True,
            )
            deadline = time.monotonic() + args.timeout
        if refreshed_dialog == "treasure" and not refreshed_ready:
            blocked_screen = "treasure"
            active_dialog = None
            refreshed_state = parse_state(
                read_log_tail(log_path, run_log_offset)
            ) if args.layout == "deluxe" else None
            treasure_state = refreshed_state or deluxe_state
            slots = None
            if treasure_state is not None:
                slots = treasure_slots_for_state(treasure_state)
            if slots is None:
                contexts = list(TREASURE_CONTEXT_RE.finditer(startup_text))
                if contexts and contexts[-1].group("book") != "nil":
                    slots = treasure_slots_for_context(
                        int(contexts[-1].group("book")),
                        int(contexts[-1].group("selected")),
                    )
            if slots is not None:
                log_message(
                    f"Recovering startup treasure screen with slots {slots}.",
                    flush=True,
                )
                treasure_selection_started = True
                controller.select_treasures(slots, args.delay)
        map_matches = list(CHAPTER_MAP_RE.finditer(
            startup_text
        ))
        unresolved_prompt = latest_unresolved_minigame_prompt(startup_text)
        if unresolved_prompt is not None:
            log_message(
                "Recovering Lua-confirmed mini-game prompt; choosing Yes to skip it.",
                flush=True,
            )
            time.sleep(max(0.8, args.delay))
            controller.confirm_skip_minigame(max(0.8, args.delay))
            pending_minigame_prompt = int(
                unresolved_prompt.group("sequence")
            )
            handled_minigame_prompts.add(pending_minigame_prompt)
            minigame_prompt_attempts = 1
            minigame_prompt_retry_at = time.monotonic() + 1.5
            deadline = time.monotonic() + args.timeout
        elif map_matches and map_matches[-1].group("enabled") == "true":
            selected = int(map_matches[-1].group("selected"))
            log_message(
                f"Recovering ready chapter map for Chapter {selected}; entering.",
                flush=True,
            )
            chapter_enter_attempts = 1
            # CHAPTER_MAP is the native input gate. Do not block the log
            # follower after clicking: the disabled-map/start-game events are
            # both safer and faster than a blind one-second guard.
            controller.enter_chapter(0.0)
            deadline = time.monotonic() + args.timeout
        while True:
            token_is_new = (
                deluxe_state is not None
                and deluxe_state.sequence != attack.sequence
                if args.layout == "deluxe" else board != attack.board
            )
            if (
                ready and board and token_is_new
                and (args.layout != "deluxe" or deluxe_state is None
                     or ready_sequence_is_fresh(deluxe_state.sequence, required_ready_after_overlay))
                and active_dialog is None and blocked_screen is None
                and not menu_reentry_pending and not chapter_enter_pending
                and time.monotonic() >= ready_at
            ):
                path = None
                if args.layout == "deluxe":
                    if deluxe_state is None or deluxe_state.board != board:
                        recovered = parse_state(
                            read_log_tail(log_path, run_log_offset)
                        )
                        if recovered is not None and recovered.board == board:
                            deluxe_state = recovered
                            log_message(
                                f"Complete state {recovered.sequence} recovered "
                                "for early READY event.",
                                flush=True,
                            )
                        else:
                            early_ready_board = board
                            ready = False
                            log_message(
                                "READY arrived before its complete Deluxe snapshot; "
                                "waiting for state recovery.",
                                flush=True,
                            )
                            continue
                    if (attack.acknowledged and attack.native_authorized
                            and is_unchanged_combat_snapshot(deluxe_state, attack.state)):
                        log_message(
                            f"Ignoring unchanged READY snapshot "
                            f"{deluxe_state.sequence} for {deluxe_state.enemy}.",
                            flush=True,
                        )
                        attack.sequence = deluxe_state.sequence
                        ready = False
                        continue
                    rejected_words_context = refresh_rejected_words_context(
                        rejected_words, rejected_words_context, deluxe_state,
                    )
                    prefetched_words = rack_prefetch.take(deluxe_state.board)
                    if prefetched_words is not None:
                        log_message(
                            f"Using {len(prefetched_words)} prefetched rack words; "
                            "rescoring against the confirmed live state.", flush=True,
                        )
                    ranked = [
                        candidate for candidate in candidates(
                            deluxe_state,
                            prefetched_words if prefetched_words is not None else deluxe_words,
                            metal_words, args.delay
                        )
                        if (
                            candidate.word not in rejected_words
                            and enemy_accepts_candidate(deluxe_state, candidate)
                        )
                    ]
                    if not ranked:
                        # Sphinx answers are guaranteed to appear in the
                        # rotating board; let Lua publish the next board
                        # instead of spending a scramble on a temporary miss.
                        if SPHINX_ANSWERS.get(deluxe_state.enemy) is not None:
                            log_message(
                                f"Sphinx answer {SPHINX_ANSWERS[deluxe_state.enemy]} "
                                "not on this board; waiting for Lua board rotation.",
                                flush=True,
                            )
                            attack.board = board
                            attack.sequence = deluxe_state.sequence
                            ready = False
                            deadline = time.monotonic() + args.timeout
                            continue
                        if scrambles >= args.max_scrambles:
                            raise RuntimeError(
                                f"Stopped after the safety limit of {args.max_scrambles} scrambles"
                            )
                        scrambles += 1
                        log_message(
                            f"State {deluxe_state.sequence}: no playable word; "
                            f"Scramble {scrambles}/{args.max_scrambles}.",
                            flush=True,
                        )
                        controller.scramble(args.delay)
                        attack.board = board
                        attack.sequence = deluxe_state.sequence
                        ready = False
                        deadline = time.monotonic() + args.timeout
                        continue
                    requested_strategy = args.strategy
                    effective_strategy = strategy_for_state(
                        deluxe_state,
                        "chapter-aware"
                        if requested_strategy == "book1-lookahead"
                        else requested_strategy,
                        chapter,
                    )
                    effective_strategy = boss_finish_strategy(
                        deluxe_state, effective_strategy, ranked
                    )
                    selected, alternatives = choose(ranked, effective_strategy)
                    experimental = decision_overrides.choose(deluxe_state, ranked)
                    if experimental is not None:
                        selected = experimental
                        effective_strategy = "book1-experiment"
                        log_message(
                            "  experiment: applying exact-state decision "
                            f"{selected.word}/{selected.path}.", flush=True,
                        )
                    elif (
                        requested_strategy == "book1-lookahead"
                        and deluxe_state.book == 1
                        and 1 <= deluxe_state.chapter <= 5
                    ):
                        lookahead = choose_recorded_lookahead(
                            deluxe_state, ranked, transition_corpus
                        )
                        if lookahead is None:
                            log_message(
                                "  lookahead: fewer than two validated branches; "
                                f"falling back to {effective_strategy}.",
                                flush=True,
                            )
                        else:
                            selected = lookahead
                            effective_strategy = "book1-lookahead"
                            log_message(
                                "  lookahead: selected from validated recorded "
                                "successors.", flush=True,
                            )
                    riddle_candidate, riddle_answer = sphinx_candidate(
                        deluxe_state.enemy, ranked
                    )
                    if riddle_candidate is not None:
                        selected = riddle_candidate
                        log_message(
                            f"  Sphinx override: using fixed answer {riddle_answer}.",
                            flush=True,
                        )
                    elif riddle_answer is not None:
                        if sphinx_allows_damage_fallback(
                            deluxe_state.enemy, selected
                        ):
                            log_message(
                                f"  Sphinx answer {riddle_answer} is absent; "
                                f"using normal combat word {selected.word}.",
                                flush=True,
                            )
                            word, damage, path = (
                                selected.word, selected.damage, selected.path
                            )
                        else:
                            log_message(
                                f"  Sphinx answer {riddle_answer} is not playable; "
                                "waiting for Lua puzzle-board rotation.",
                                flush=True,
                            )
                            attack.board = board
                            attack.sequence = deluxe_state.sequence
                            ready = False
                            deadline = time.monotonic() + args.timeout
                            continue
                    word, damage, path = selected.word, selected.damage, selected.path
                    shortest = alternatives.get("shortest_lethal")
                    maximum = alternatives["max_damage"]
                    log_message(
                        f"State {deluxe_state.sequence}: {deluxe_state.enemy} "
                        f"HP {deluxe_state.hp:g}/{deluxe_state.max_hp:g}; "
                        f"treasures={','.join(sorted(deluxe_state.treasures)) or 'none'}",
                        flush=True,
                    )
                    warning = validate_chapter1_state(deluxe_state, chapter1_hp)
                    if warning:
                        log_message(f"  state warning: {warning}", flush=True)
                    log_message(
                        f"  chose {word} damage={damage:.2f} "
                        f"overkill={selected.overkill:.2f} tier={selected.tier} "
                        f"animation={selected.animation_class} "
                        f"gems={','.join(selected.gem_types) or 'none'} "
                        f"strategy={effective_strategy} "
                        f"time={selected.predicted_time:.2f}s; "
                        f"shortest={shortest.word if shortest else 'none'}; "
                        f"max={maximum.word}",
                        flush=True,
                    )
                else:
                    word, damage = best_word(board)
                if (
                    args.layout == "deluxe" and deluxe_state is not None
                    and should_use_health_potion(deluxe_state, selected)
                ):
                    log_message(
                        f"Health potion required at "
                        f"{deluxe_state.player_hp:g}/"
                        f"{deluxe_state.player_max_hp:g}; waiting for native "
                        "consumption confirmation before attacking.",
                        flush=True,
                    )
                    controller.use_health_potion(max(0.8, args.delay))
                    pending_health_potion_state = deluxe_state
                    pending_health_potion_attempts = 1
                    pending_health_potion_at = time.monotonic() + 1.5
                    attack.board = board
                    attack.sequence = deluxe_state.sequence
                    ready = False
                    deadline = time.monotonic() + args.timeout
                    continue
                attacks += 1
                log_message(
                    f"Attack {attacks}: {board} -> {word.upper()} "
                    f"({damage:.2f} estimated damage)",
                    flush=True,
                )
                if (
                    args.layout == "deluxe" and deluxe_state is not None
                    and should_use_powerup_potion(deluxe_state, selected)
                ):
                    log_message(
                        "Power-Up converts the selected attack into a predicted "
                        "one-shot; activating it.",
                        flush=True,
                    )
                    if not activate_powerup_when_native_ready(
                        controller, log_path, args.delay,
                    ):
                        log_message(
                            "Power-Up did not reach its native input-ready "
                            "state; leaving the rack untouched.", flush=True,
                        )
                        attack.board = board
                        attack.sequence = deluxe_state.sequence
                        ready = False
                        deadline = time.monotonic() + args.timeout
                        continue
                    log_message(
                        "Native Power-Up activation confirmed; selecting the "
                        "finishing word.", flush=True,
                    )
                if (
                    args.layout == "deluxe" and deluxe_state is not None
                    and should_use_purification_potion(deluxe_state, selected)
                ):
                    # Petrify can end an encounter with Lex still at full
                    # health. Cleanse it before submitting the next word.
                    log_message(
                        "Purify required before attack: "
                        f"enemy={deluxe_state.enemy}; "
                        f"petrified={int(deluxe_state.player_petrified)}; "
                        "damage_over_time="
                        f"{int(deluxe_state.player_has_damage_over_time)}.",
                        flush=True,
                    )
                    controller.use_purification_potion(max(0.8, args.delay))
                attack_started_at = time.monotonic()
                attack.native_authorized = False
                if args.layout == "deluxe":
                    native_ready = select_and_attack_when_native_ready(
                        controller, log_path, board, word,
                        tile_input_delay(deluxe_state, args.tile_delay), path,
                    )
                    attack.native_authorized = native_ready
                    attack_clicked_at = (
                        getattr(
                            controller, "last_attack_key_sent_at",
                            time.monotonic(),
                        )
                        if native_ready else None
                    )
                    if not native_ready:
                        log_message(
                            "Native selection did not reach the complete valid "
                            "word; Attack was not clicked.", flush=True,
                        )
                else:
                    controller.play_word(
                        board, word, args.delay, args.settle, path,
                        clear_first=False,
                    )
                    attack_clicked_at = getattr(
                        controller, "last_attack_key_sent_at", time.monotonic()
                    )
                attack.begin_submission(board, word, path)
                ready_latency_ms = getattr(
                    controller, "last_attack_ready_latency_ms", float("inf")
                )
                if attack.native_authorized and ready_latency_ms < 250:
                    # This is the engine's brief false-idle gap before some
                    # word presentations. The immediate Enter is worthwhile,
                    # but if it is discarded, preserve the live selection long
                    # enough for Lua to issue the post-presentation edge.
                    attack.retry_at = time.monotonic() + max(
                        4.0, args.input_confirm_timeout
                    )
                    log_message(
                        f"Early native Attack edge ({ready_latency_ms:.1f} ms); "
                        "using bounded 10 ms Enter retries while preserving the "
                        "selected rack.",
                        flush=True,
                    )
                elif not attack.native_authorized:
                    # The helper already waited for a complete native
                    # selection. Retry on the next loop iteration instead of
                    # adding the outer acknowledgement timeout to that miss.
                    attack.retry_at = time.monotonic()
                else:
                    attack.retry_at = (
                        time.monotonic() + args.input_confirm_timeout
                    )
                if deluxe_state is not None:
                    attack.sequence = deluxe_state.sequence
                    attack.book, attack.chapter = telemetry_context(
                        deluxe_state, timer_state,
                    )
                    attack.started_at = attack_started_at
                    attack.attack_sent_at = attack_clicked_at
                    attack.candidate = selected
                    attack.state = deluxe_state
                    native_attack_events = []
                    last_attack_state = deluxe_state
                    attack.strategy = effective_strategy
                    attack.frontier = list(ranked)
                    attack.kill_timing_logged = False
                ready = False
                deadline = time.monotonic() + args.timeout

            # Incapacitation telemetry can arrive continuously while a modal
            # animation loops. Run this retry clock before reading the next
            # line so log traffic cannot starve Purify recovery.
            if (
                player_incapacitated
                and time.monotonic() >= incap_overlay_retry_at
            ):
                if incap_purify_pending:
                    if incap_purify_attempts < 3:
                        incap_purify_attempts += 1
                        log_message(
                            "Purify is still unconfirmed; retrying the "
                            f"blue potion ({incap_purify_attempts}/3).",
                            flush=True,
                        )
                        controller.use_purification_potion(
                            max(0.8, args.delay)
                        )
                    else:
                        log_message(
                            "Purify remained unconfirmed after 3 attempts; "
                            "falling back to lost-turn recovery.",
                            flush=True,
                        )
                        incap_purify_pending = False
                        incap_purify_failed = True
                        controller.dismiss_incapacitation_overlay(args.delay)
                else:
                    log_message(
                        "Native incapacitation overlay is still active; "
                        "retrying its continuation click.",
                        flush=True,
                    )
                    controller.dismiss_incapacitation_overlay(args.delay)
                incap_overlay_retry_at = time.monotonic() + 1.0
                deadline = time.monotonic() + args.timeout

            line = log.readline()
            if not line:
                if (
                    args.auto_dialog
                    and not ready
                    and active_dialog in {None, "convpanel"}
                    and blocked_screen is None
                    and not player_incapacitated
                    and boss_reset_state is None
                    and not menu_reentry_pending
                    and not chapter_enter_pending
                    and time.monotonic() >= dialog_probe_at
                ):
                    dialog_probe_count += 1
                    log_message(
                        "No READY event after board update; probing the safe "
                        f"dialogue point ({dialog_probe_count}).",
                        flush=True,
                    )
                    controller.advance_dialog(
                        active_dialog or "interrupt", args.delay,
                    )
                    dialog_probe_at = (
                        time.monotonic() + args.dialog_probe_interval
                    )
                if (
                    pending_health_potion_state is not None
                    and time.monotonic() >= pending_health_potion_at
                ):
                    if pending_health_potion_attempts >= 3:
                        raise RuntimeError(
                            "Health potion was not confirmed after 3 safe retries; "
                            "refusing to submit the attack"
                        )
                    pending_health_potion_attempts += 1
                    log_message(
                        "No native health-potion confirmation; retrying "
                        f"({pending_health_potion_attempts}/3).",
                        flush=True,
                    )
                    controller.use_health_potion(max(0.8, args.delay))
                    pending_health_potion_at = time.monotonic() + 1.5
                    deadline = time.monotonic() + args.timeout
                if menu_reentry_pending and time.monotonic() >= menu_reentry_at:
                    if book_transition_dialog_click_required(
                        last_boss_reset_key, menu_reentry_dialog_clicks,
                    ):
                        menu_reentry_dialog_clicks += 1
                        log_message(
                            "Advancing post-Book 1 Lex dialogue "
                            f"({menu_reentry_dialog_clicks}/2).",
                            flush=True,
                        )
                        controller.advance_dialog("interrupt", args.delay)
                        menu_reentry_at = time.monotonic() + 1.0
                    else:
                        menu_reentry_attempts += 1
                        log_message(
                            "Retrying Adventure while awaiting Lua map acknowledgement "
                            f"({menu_reentry_attempts}).",
                            flush=True,
                        )
                        controller.start_adventure(args.delay)
                        menu_reentry_at = (
                            time.monotonic() + MENU_REENTRY_RETRY_SECONDS
                        )
                    deadline = time.monotonic() + args.timeout
                if should_retry_minigame_prompt(
                    pending_minigame_prompt, minigame_prompt_attempts,
                    time.monotonic(), minigame_prompt_retry_at,
                ):
                    minigame_prompt_attempts += 1
                    log_message(
                        "Mini-game skip remains unconfirmed; retrying Yes "
                        f"({minigame_prompt_attempts}/5).",
                        flush=True,
                    )
                    controller.confirm_skip_minigame(max(0.8, args.delay))
                    minigame_prompt_retry_at = time.monotonic() + 1.5
                    deadline = time.monotonic() + args.timeout
                if chapter_enter_pending and time.monotonic() >= chapter_enter_at:
                    chapter_enter_attempts += 1
                    log_message(
                        "Entering the next chapter from the chapter map "
                        f"(attempt {chapter_enter_attempts}/20).",
                        flush=True,
                    )
                    # Map animations can still own the Enter hotspot when the
                    # epilogue's final Lua event arrives. Retry conservatively;
                    # every fresh board/dialog/chapter event below disarms it.
                    chapter_enter_pending = chapter_enter_attempts < 20
                    chapter_enter_at = (
                        time.monotonic() + 3.0
                        if chapter_enter_pending else float("inf")
                    )
                    controller.enter_chapter(0.0)
                    dialog_probe_at = time.monotonic() + args.dialog_stall_delay
                    deadline = time.monotonic() + args.timeout
                if (
                    not tutorial_play_submitted
                    and is_initial_play_tutorial(
                        board, active_dialog, deluxe_state, attacks
                    )
                ):
                    tutorial_play_submitted = True
                    log_message("Completing fixed fresh-profile PLAY tutorial.", flush=True)
                    # Native PLAY_READY events own every tutorial tile. Keep
                    # generic recovery away from the rack during the handoff.
                    dialog_probe_at = float("inf")
                    deadline = time.monotonic() + args.timeout
                    time.sleep(args.poll)
                    continue
                if attack.retry_is_due(
                    time.monotonic(),
                    input_blocked=(player_incapacitated or active_dialog is not None
                                   or blocked_screen is not None),
                ):
                    if attack.attempts >= args.max_input_attempts:
                        assert attack.word is not None
                        if args.layout == "deluxe":
                            raise RuntimeError(
                                f"Native input failed for {attack.word.upper()} after "
                                f"{attack.attempts} attempts, including confirmed-tile retries; "
                                "stopping without blacklisting words or sending more clicks"
                            )
                        rejected_words.add(attack.word)
                        log_message(
                            f"Blacklisting unacknowledged word "
                            f"{attack.word.upper()} after {attack.attempts} attempts; "
                            "trying the next candidate.",
                            flush=True,
                        )
                        controller.dismiss_invalid_word_dialog(args.delay)
                        attack.sequence = None
                        attack.state = None
                        attack.candidate = None
                        attack.word = None
                        attack.path = None
                        attack.acknowledged = True
                        attack.retry_at = float("inf")
                        ready = True
                        ready_at = time.monotonic() + args.ready_delay
                        continue
                    assert attack.word is not None and attack.board is not None
                    attack.attempts += 1
                    if timer_state is not None:
                        mark_current_issue(
                            timer_state,
                            f"input-retry:{attack.word.upper()}",
                        )
                        save_timer_state(args.timer_state, timer_state)
                        save_run_history(timer_state)
                    log_message(
                        f"No ATTACK acknowledgement; clearing and retrying "
                        f"{attack.word.upper()} ({attack.attempts}/{args.max_input_attempts}).",
                        flush=True,
                    )
                    controller.dismiss_invalid_word_dialog(args.delay)
                    retry_delay = args.tile_delay * attack.attempts
                    if args.layout == "deluxe":
                        native_ready = select_and_attack_when_native_ready(
                            controller, log_path, attack.board,
                            attack.word,
                            tile_input_delay(attack.state, retry_delay),
                            attack.path,
                            confirm_each_tile=True,
                        )
                        attack.native_authorized = native_ready
                        if native_ready:
                            attack.native_authorized = True
                            attack.attack_sent_at = getattr(
                                controller, "last_attack_key_sent_at",
                                time.monotonic(),
                            )
                        else:
                            log_message(
                                "Native selection did not reach the complete "
                                "valid word; Attack was not clicked.", flush=True,
                            )
                    else:
                        controller.play_word(
                            attack.board, attack.word, retry_delay,
                            args.settle, attack.path,
                        )
                    attack.retry_at = time.monotonic() + args.input_confirm_timeout
                if args.layout == "deluxe":
                    polled_state = parse_state(
                        read_log_tail(log_path, run_log_offset)
                    )
                    if (
                        polled_state is not None
                        # A whole-file read can see events appended while a
                        # blocking input helper ran. Drain those events first;
                        # they may contain an overlay before this READY.
                        and polled_state.sequence <= stream_ready_sequence
                        and (
                            deluxe_state is None
                            or polled_state.sequence > deluxe_state.sequence
                        )
                    ):
                        deluxe_state = polled_state
                        board = polled_state.board
                        ready = True
                        ready_at = time.monotonic() + args.ready_delay
                        log_message(
                            f"Complete state {polled_state.sequence} recovered from log.",
                            flush=True,
                        )
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for the next combat log event")
                time.sleep(args.poll)
                continue

            line = line.rstrip("\r\n")
            stream_ready_sequence = streamed_ready_sequence(line, stream_ready_sequence)
            dialog_active = DIALOG_ACTIVE_RE.search(line)
            if dialog_active:
                active_dialog = dialog_active.group("source")
                conversation_after_treasure = (
                    post_treasure_convpanel_supersedes_boss_reset(
                        active_dialog, blocked_screen,
                        treasure_selection_started,
                    )
                )
                attack.presentation_active = bool(
                    active_dialog == "interrupt"
                    and not attack.acknowledged
                    and attack.native_authorized
                )
                if attack.presentation_active:
                    attack.presentation_pending_submit = True
                    log_message(
                        "Completed-word presentation started; preserving the "
                        "selection for its second native Enter edge.", flush=True,
                    )
                    continue
                if convpanel_supersedes_navigation_transition(active_dialog):
                    menu_reentry_pending = False
                    menu_reentry_at = float("inf")
                    chapter_enter_pending = False
                    chapter_enter_at = float("inf")
                    # Some post-boss panels publish ACTIVE but no PULSE. Arm
                    # the bounded safe-point fallback while Lua still proves
                    # this panel owns input.
                    dialog_probe_at = time.monotonic() + args.dialog_stall_delay
                    dialog_probe_count = 0
                if conversation_after_treasure and boss_reset_state is not None:
                    log_message(
                        "Native post-treasure conversation superseded stale "
                        "boss-reset suppression; dialogue pulses rearmed.",
                        flush=True,
                    )
                    boss_reset_state = None
                    boss_reset_dialog_ready = False
                pending_health_potion_state = None
                pending_health_potion_at = float("inf")
                pending_health_potion_attempts = 0
                old_blocked_screen = blocked_screen
                old_treasure_selection = treasure_selection_started
                blocked_screen, treasure_selection_started = (
                    clear_stale_treasure_transition(
                        active_dialog, blocked_screen, treasure_selection_started
                    )
                )
                if (
                    old_blocked_screen == "treasure" or old_treasure_selection
                ) and blocked_screen is None and not treasure_selection_started:
                    log_message(
                        "Native conversation superseded stale treasure "
                        "transition; dialogue pulses rearmed.",
                        flush=True,
                    )
                ready = False
                attack.retry_at = float("inf")
                if deluxe_state is not None:
                    required_ready_after_overlay = max(
                        required_ready_after_overlay or -1,
                        stream_ready_sequence,
                    )
                if not attack.acknowledged:
                    log_message(
                        "Dialogue interrupted pending tile input; discarding "
                        "it until a newer READY sequence.", flush=True,
                    )
                    attack.discard_interrupted_selection()
                if (
                    not tutorial_play_submitted
                    and is_initial_play_tutorial(
                        board, active_dialog, deluxe_state, attacks
                    )
                ):
                    tutorial_play_submitted = True
                    log_message("Completing fixed fresh-profile PLAY tutorial.", flush=True)
                    deadline = time.monotonic() + args.timeout
            play_tutorial = PLAY_TUTORIAL_RE.search(line)
            if play_tutorial and not tutorial_play_submitted:
                tutorial_play_submitted = True
                tutorial_interrupt_active = True
                active_dialog = "interrupt"
                log_message("Completing fixed fresh-profile PLAY tutorial.", flush=True)
                deadline = time.monotonic() + args.timeout
            play_ready = PLAY_READY_RE.search(line)
            if play_ready:
                letter = play_ready.group("letter")
                pulse = int(play_ready.group("pulse"))
                tutorial_play_submitted = True
                # DONE still belongs to IntroTutorial until its interrupt edge
                # closes; generic dialogue pulses must remain suppressed.
                tutorial_interrupt_active = True
                # Tile steps are single-shot once their native selection gate
                # opens. The final Attack button is different: mNextLetter is
                # cleared before its button animation accepts MouseUp, so its
                # retries remain safe (an empty live rack cannot attack).
                if letter == "DONE" or letter != last_play_letter_clicked:
                    log_message(
                        f"Native PLAY step {letter} ready (attempt {pulse}); "
                        "clicking it once.", flush=True,
                    )
                    # IntroTutorial changes mNextLetter synchronously after an
                    # accepted MouseUp, so Lua authorizes the next coordinate.
                    # The general 80 ms UI delay only serialized these five
                    # otherwise independent native steps.
                    controller.play_tutorial_step(letter, min(args.delay, 0.01))
                    last_play_letter_clicked = letter
                deadline = time.monotonic() + args.timeout
            dialog_inactive = DIALOG_INACTIVE_RE.search(line)
            if dialog_inactive:
                active_dialog = None
                tutorial_interrupt_active = False
                attack.presentation_active = False
                if menu_reset_dialog_seen and menu_reentry_pending:
                    log_message(
                        "Post-boss result overlay closed after blocking the "
                        "menu exit; retrying the full battle-menu reset.",
                        flush=True,
                    )
                    reset_from_battle(
                        controller, RESET_MENU_TIMING, telemetry_log=args.log, trace=menu_trace,
                    )
                    menu_reset_dialog_seen = False
                    menu_reentry_attempts = 0
                    menu_reentry_dialog_clicks = 0
                    menu_reentry_at = (
                        time.monotonic() + MENU_REENTRY_RETRY_SECONDS
                    )
                    deadline = time.monotonic() + args.timeout
                if required_ready_after_overlay is not None:
                    log_message(
                        "Dialogue exited; waiting for a newer native READY "
                        "sequence before touching the rack.", flush=True,
                    )
            attack_ready = ATTACK_READY_RE.search(line)
            if (
                attack_ready
                and attack.presentation_pending_submit
                and not attack.acknowledged
                and attack.word is not None
                and int(attack_ready.group("count"))
                == len(attack.path or attack.word)
            ):
                second_ready_at = time.monotonic()
                controller.click_attack(args.delay)
                second_enter_at = getattr(
                    controller, "last_attack_key_sent_at", second_ready_at
                )
                log_message(
                    f"Attack timing {attack.word.upper()}: "
                    "post-presentation_enter_sent; "
                    "ready_to_enter_ms="
                    f"{(second_enter_at - second_ready_at) * 1000:.1f}",
                    flush=True,
                )
                log_message(
                    "Completed-word presentation released; submitting the "
                    "preserved selection without retyping.", flush=True,
                )
                attack.presentation_pending_submit = False
                attack.attack_sent_at = second_enter_at
                attack.retry_at = (
                    time.monotonic() + args.input_confirm_timeout
                )
                deadline = time.monotonic() + args.timeout
            dialog_pulse = DIALOG_PULSE_RE.search(line)
            if dialog_pulse and args.auto_dialog:
                source = dialog_pulse.group("source")
                pulse = int(dialog_pulse.group("pulse"))
                recover_blocked_reset = boss_reset_dialog_recovery_allowed(
                    source, menu_reentry_pending, last_boss_reset_key
                )
                suppress = dialogue_pulse_suppressed(
                    boss_reset_state is not None,
                    blocked_screen == "treasure" or treasure_selection_started,
                    chapter_enter_pending or chapter_enter_at != float("inf"),
                    (menu_reentry_pending or menu_reentry_at != float("inf"))
                    and not recover_blocked_reset,
                    not attack.acknowledged and attack.word is not None,
                )
                # PLAY is submitted through its fixed rack, never by clicking
                # the generic interrupt target over the lesson.
                if source == "interrupt" and (
                    board == TUTORIAL_PLAY_BOARD or tutorial_interrupt_active
                ):
                    suppress = True
                if attack.presentation_active:
                    suppress = True
                if suppress:
                    log_message(
                        f"Lua dialogue pulse {pulse}: source={source}; "
                        "suppressed during special-screen transition.", flush=True,
                    )
                else:
                    if recover_blocked_reset:
                        menu_reset_dialog_seen = True
                    destination = (
                        "Continue" if source == "levelup" else "safe arena point"
                    )
                    log_message(
                        f"Lua dialogue pulse {pulse}: source={source}; "
                        f"clicking {destination}.", flush=True,
                    )
                    # Lua has already confirmed the exact MouseUp owner. Keep
                    # only a 10 ms event-delivery guard; waiting the generic
                    # non-rack UI delay here costs time on every dialogue page.
                    controller.advance_dialog(source, min(args.delay, 0.01))
                    dialog_probe_at = (
                        time.monotonic() + args.dialog_probe_interval
                    )
            stunned_event = PLAYER_STUNNED_RE.search(line)
            if stunned_event and stunned_event.group("active") == "1":
                incapacitation = stunned_event.group("kind").casefold()
                player_incapacitated = True
                attack.retry_at = float("inf")
                ready = False
                if deluxe_state is not None:
                    required_ready_after_overlay = max(
                        required_ready_after_overlay or -1,
                        stream_ready_sequence,
                    )
                if not attack.acknowledged:
                    log_message(
                        "Incapacitation interrupted pending tile input; "
                        "discarding it until a newer READY sequence.", flush=True,
                    )
                    attack.discard_interrupted_selection()
                purify_available = (
                    stunned_event.group("purify_potion") == "1"
                    if stunned_event.group("purify_potion") is not None
                    else False
                )
                live_hp = (
                    float(stunned_event.group("hp"))
                    if stunned_event.group("hp") is not None else -1
                )
                live_max_hp = (
                    float(stunned_event.group("max_hp"))
                    if stunned_event.group("max_hp") is not None else -1
                )
                health_available = (
                    stunned_event.group("health_potion") == "1"
                    if stunned_event.group("health_potion") is not None
                    else False
                )
                recovery = incapacitation_recovery_action(
                    purify_available=purify_available,
                    health_available=health_available,
                    player_hp=live_hp,
                    player_max_hp=live_max_hp,
                )
                if (
                    recovery == "purify" and not incap_purify_pending
                    and not incap_purify_failed
                ):
                    log_message(
                        f"Lua confirmed Lex is {incapacitation} and Purify is "
                        "available; cancelling the lost-turn status.",
                        flush=True,
                    )
                    controller.use_purification_potion(max(0.8, args.delay))
                    incap_purify_pending = True
                    incap_purify_attempts = 1
                    incap_overlay_retry_at = time.monotonic() + 1.0
                elif recovery == "heal_then_continue" and not incap_health_submitted:
                    log_message(
                        f"Purify unavailable and Lex is at {live_hp:g}/"
                        f"{live_max_hp:g}; using a confirmed health potion "
                        "before accepting the lost turn.",
                        flush=True,
                    )
                    controller.use_health_potion(max(0.8, args.delay))
                    incap_health_submitted = True
                elif not incap_purify_pending:
                    log_message(
                        f"Lua confirmed Lex is {incapacitation}; Purify is "
                        "unavailable, waiting for the native grid overlay.",
                        flush=True,
                    )
            elif (
                stunned_event and stunned_event.group("active") == "0"
            ):
                player_incapacitated = False
                incap_purify_pending = False
                incap_purify_attempts = 0
                incap_purify_failed = False
                incap_health_submitted = False
                incap_overlay_retry_at = float("inf")
                log_message(
                    "Lua confirmed incapacitation ended; no further overlay "
                    "click is safe after UI ownership returns to the rack.",
                    flush=True,
                )
                deadline = time.monotonic() + args.timeout
                log_message(
                    "Incapacitation cleared; waiting for a newer native READY "
                    "sequence before touching the rack.", flush=True,
                )
            incap_overlay_event = INCAP_OVERLAY_RE.search(line)
            if incap_overlay_event:
                if incap_purify_pending:
                    frame = incap_overlay_event.group("frame")
                    if frame.endswith("done") and incap_purify_attempts < 3:
                        incap_purify_attempts += 1
                        log_message(
                            f"Native {frame} frame is stable and Purify is "
                            f"unconfirmed; retrying the blue potion "
                            f"({incap_purify_attempts}/3).",
                            flush=True,
                        )
                        controller.use_purification_potion(
                            max(0.8, args.delay)
                        )
                        incap_overlay_retry_at = time.monotonic() + 1.0
                    else:
                        log_message(
                            "Native incapacitation overlay remains active while "
                            "Purify confirmation is pending; continuation click "
                            "suppressed.",
                            flush=True,
                        )
                else:
                    overlay_hp = (
                        float(incap_overlay_event.group("hp"))
                        if incap_overlay_event.group("hp") is not None else -1
                    )
                    overlay_max_hp = (
                        float(incap_overlay_event.group("max_hp"))
                        if incap_overlay_event.group("max_hp") is not None else -1
                    )
                    must_heal = (
                        incap_purify_failed
                        and incap_overlay_event.group("health_potion") == "1"
                        and 0 < overlay_hp <= min(4.0, overlay_max_hp)
                        and not incap_health_submitted
                    )
                    if must_heal:
                        log_message(
                            f"Purify failed and Lex fell to {overlay_hp:g}/"
                            f"{overlay_max_hp:g}; healing before accepting "
                            "the next lost turn.",
                            flush=True,
                        )
                        controller.use_health_potion(max(0.8, args.delay))
                        incap_health_submitted = True
                    log_message(
                        "Lua confirmed the native "
                        f"{incap_overlay_event.group('kind')} overlay is active "
                        f"(frame {incap_overlay_event.group('frame')}); "
                        "clicking its continuation area.",
                        flush=True,
                    )
                    controller.dismiss_incapacitation_overlay(args.delay)
                # The frame edge can arrive while the card is still animating,
                # before MouseUp accepts the click. Keep pulsing until Lua
                # reports that the native incapacitation predicate cleared.
                incap_overlay_retry_at = time.monotonic() + 1.0
            if timer_state is not None and process_timer_line(
                timer_state, line, time.time()
            ):
                save_timer_state(args.timer_state, timer_state)
                save_run_history(timer_state)
                update_tas_best(timer_state)
                timed = timer_state["current"]
                if timed is None and timer_state.get("finished_at") is not None:
                    log_message(
                        "Run timer finished at Codex's native zero-HP edge.",
                        flush=True,
                    )
                else:
                    log_message(
                        f"Timer entered Book {timed['book']} Chapter "
                        f"{timed['chapter']}.",
                        flush=True,
                    )
            map_event = CHAPTER_MAP_RE.search(line)
            if map_event:
                selected = int(map_event.group("selected"))
                map_enabled = map_event.group("enabled") == "true"
                if menu_trace:
                    menu_trace.event('chapter_map_observed', selected=selected,
                                     enabled=map_enabled, source='Lua BookManager')
                if chapter_map_confirms_menu_reentry(map_enabled):
                    menu_reentry_pending = False
                    menu_reentry_at = float("inf")
                if map_enabled:
                    chapter = selected if selected >= 1 else chapter
                    chapter_enter_attempts += 1
                    log_message(
                        f"Chapter map ready for Chapter {selected}; entering "
                        f"(event {chapter_enter_attempts}).",
                        flush=True,
                    )
                    controller.enter_chapter(0.0)
                    dialog_probe_at = float("inf")
                    deadline = time.monotonic() + args.timeout
                else:
                    log_message(
                        f"Chapter {selected} map has Enter disabled; waiting for native readiness or the next screen.",
                        flush=True,
                    )
                    chapter_enter_pending = False
                    chapter_enter_at = float("inf")
            action_event = CHAPTER_ACTION_RE.search(line)
            if action_event:
                action = action_event.group("action")
                if menu_trace:
                    menu_trace.event('chapter_callback_observed', action=action)
                was_menu_reentry = menu_reentry_pending
                if action == "continue":
                    menu_reentry_pending = False
                    menu_reentry_at = float("inf")
                    chapter_enter_pending = False
                    chapter_enter_at = float("inf")
                if action == "minigame-callback":
                    pending_minigame_prompt = None
                    minigame_prompt_retry_at = float("inf")
                old_boss_reset = boss_reset_state
                old_blocked_screen = blocked_screen
                old_treasure_selection = treasure_selection_started
                boss_reset_state, blocked_screen, treasure_selection_started = (
                    clear_special_transitions_on_chapter_start(
                        action, boss_reset_state, blocked_screen,
                        treasure_selection_started,
                    )
                )
                if action == "start-game":
                    boss_reset_dialog_ready = False
                    menu_reentry_pending = False
                    menu_reentry_at = float("inf")
                    chapter_enter_pending = False
                    chapter_enter_at = float("inf")
                    if was_menu_reentry:
                        # The opening War Hound state can precede its tutorial
                        # overlay by one log line. Preserve a small native
                        # handoff window so the overlay wins before rack input.
                        ready_at = max(
                            ready_at, time.monotonic() + 1.25,
                        )
                        if menu_trace:
                            menu_trace.event('reentry_ready_guard_armed', seconds=1.25)
                    if (
                        old_boss_reset is not None
                        or old_blocked_screen is not None
                        or old_treasure_selection
                    ):
                        log_message(
                            "Native chapter start cleared stale special-screen "
                            "transition state; dialogue pulses rearmed.",
                            flush=True,
                        )
                log_message(
                    f"Chapter-map action confirmed: {action}.",
                    flush=True,
                )
                deadline = time.monotonic() + args.timeout
            if LUA_WAIT_MARKER in line:
                log_message("Lua runtime entered its explicit wait; resuming with F5.", flush=True)
                controller.resume_lua_runtime(args.delay)
                deadline = time.monotonic() + args.timeout
            treasure_context = TREASURE_CONTEXT_RE.search(line)
            if (
                treasure_context and blocked_screen == "treasure"
                and args.auto_dialog and not treasure_selection_started
                and treasure_context.group("book") != "nil"
            ):
                slots = (
                    treasure_slots_for_state(deluxe_state)
                    if deluxe_state is not None else None
                )
                if slots is None:
                    slots = treasure_slots_for_context(
                        int(treasure_context.group("book")),
                        int(treasure_context.group("selected")),
                    )
                if slots is not None:
                    log_message(
                        f"Selecting route treasure slots {slots} from live "
                        "chapter context.",
                        flush=True,
                    )
                    treasure_selection_started = True
                    controller.select_treasures(slots, args.delay)
            minigame_prompt = MINIGAME_PROMPT_RE.search(line)
            if (
                minigame_prompt
                and int(minigame_prompt.group("sequence"))
                not in handled_minigame_prompts
            ):
                log_message(
                    "Lua-confirmed mini-game prompt; choosing Yes to skip it.",
                    flush=True,
                )
                # The hook runs as the prompt is being constructed. Give its
                # buttons one frame-safe pause before clicking Yes. Return to
                # the log loop immediately afterward; native chapter events
                # confirm whether the click was accepted.
                time.sleep(max(0.8, args.delay))
                controller.confirm_skip_minigame(0.0)
                pending_minigame_prompt = int(
                    minigame_prompt.group("sequence")
                )
                # The prompt owns input now, not Adventure or chapter Enter.
                menu_reentry_pending = False
                menu_reentry_at = float("inf")
                chapter_enter_pending = False
                chapter_enter_at = float("inf")
                handled_minigame_prompts.add(pending_minigame_prompt)
                minigame_prompt_attempts = 1
                minigame_prompt_retry_at = time.monotonic() + 1.5
                deadline = time.monotonic() + args.timeout
            dialog = LEGACY_SCREEN_RE.search(line)
            if dialog and dialog.group("kind") == "none":
                was_blocked = blocked_screen is not None
                blocked_screen = None
                treasure_selection_started = False
                active_dialog = None
                if not attack.acknowledged:
                    # A dialogue can appear after selection but before Attack
                    # becomes clickable. Its blocked time is not a failed input
                    # attempt; restart the full retry budget after it exits.
                    attack.attempts = 1
                    attack.retry_at = (
                        time.monotonic() + args.input_confirm_timeout
                    )
                    log_message(
                        "Input retry rearmed after dialogue exit.",
                        flush=True,
                    )
                if was_blocked and not ready:
                    dialog_probe_at = time.monotonic() + args.dialog_stall_delay
                    dialog_probe_count = 0
                    log_message(
                        "Treasure screen exited; dialogue fallback rearmed.",
                        flush=True,
                    )
                if boss_reset_state is not None and boss_reset_dialog_ready:
                    last_boss_reset_key = encounter_key(boss_reset_state)
                    last_boss_reset_sequence = max(boss_reset_state.sequence, stream_ready_sequence)
                    reset_encounters.add(last_boss_reset_key)
                    log_message(
                        f"Lua confirmed the post-defeat overlay for "
                        f"{boss_reset_state.enemy} closed; resetting through "
                        "the main menu.",
                        flush=True,
                    )
                    reset_from_battle(
                        controller, RESET_MENU_TIMING, telemetry_log=args.log, trace=menu_trace,
                    )
                    boss_reset_state = None
                    boss_reset_dialog_ready = False
                    menu_reentry_pending = True
                    menu_reentry_attempts = 0
                    menu_reentry_dialog_clicks = 0
                    menu_reentry_at = (
                        time.monotonic() + MENU_REENTRY_RETRY_SECONDS
                    )
                    attack.sequence = (
                        deluxe_state.sequence if deluxe_state is not None else None
                    )
                    attack.acknowledged = True
                    attack.retry_at = float("inf")
                    ready = False
                    dialog_probe_at = float("inf")
                    deadline = time.monotonic() + args.timeout
            elif dialog and dialog.group("kind") == "treasure":
                pending_minigame_prompt = None
                minigame_prompt_retry_at = float("inf")
                blocked_screen = "treasure"
                active_dialog = None
                # A treasure screen is definitive proof that the Adventure
                # re-entry succeeded; do not keep spraying title-screen clicks.
                menu_reentry_pending = False
                menu_reentry_at = float("inf")
                # Treasure Continue transitions directly into the next chapter.
                # A boss-epilogue map click must never race treasure selection.
                chapter_enter_pending = False
                chapter_enter_at = float("inf")
                ready = False
                # Reaching treasure selection proves the preceding combat is
                # over even if Wine mangled its ATTACK acknowledgement. Never
                # replay that combat word on this non-combat screen or later.
                attack.acknowledged = True
                attack.retry_at = float("inf")
                dialog_probe_at = float("inf")
                log_message(
                    "Treasure screen detected; automatic dialogue clicks paused.",
                    flush=True,
                )
                if args.auto_dialog and (
                    attack.state is not None or deluxe_state is not None
                ):
                    treasure_state = attack.state or deluxe_state
                    assert treasure_state is not None
                    slots = treasure_slots_for_state(treasure_state)
                    if slots is not None:
                        log_message(
                            f"Selecting route treasure slots {slots} after "
                            f"{treasure_state.enemy}.",
                            flush=True,
                        )
                        treasure_selection_started = True
                        controller.select_treasures(slots, args.delay)
            native_event_line = line[line.find("AUTOMATION_"):] if "AUTOMATION_" in line else ""
            if native_event_line.startswith(("AUTOMATION_ATTACK_ID=", "AUTOMATION_ATTACK_HP=", "AUTOMATION_RNG_RESET=",
                                "AUTOMATION_DAMAGE_TRACE=", "AUTOMATION_DAMAGE_TABLE=",
                                "AUTOMATION_READY_ATTACK=")):
                native_attack_events.append(native_event_line)
                # Keep malformed/unmatched streams bounded. Raw Lua logs retain all events.
                native_attack_events = native_attack_events[-64:]
            attack_submitted_event = ATTACK_SUBMITTED_RE.search(line)
            if attack_submitted_event or "User clicked ATTACK" in line:
                if attack.attack_sent_at is not None:
                    log_message(
                        f"Attack timing {(attack.word or 'unknown').upper()}: "
                        "submitted_ack; "
                        f"enter_to_ack_ms="
                        f"{(time.monotonic() - attack.attack_sent_at) * 1000:.1f}"
                    )
                attack.acknowledge()
                if attack.attempts > 1:
                    log_message(
                        f"ATTACK acknowledged after {attack.attempts} input attempts.",
                        flush=True,
                    )
                if attacks >= args.max_attacks:
                    raise RuntimeError(
                        f"Stopped after the safety limit of {args.max_attacks} attacks"
                    )
            zero_health_event = ZERO_HEALTH_RE.search(line)
            if (
                zero_health_event and not attack.kill_timing_logged
                and attack.attack_sent_at is not None
                and attack.candidate is not None
                and attack.state is not None
                and zero_health_event.group("enemy") == attack.state.enemy
            ):
                zero_at = time.monotonic()
                kill_sample = {
                    "record_type": "attack-to-zero-health",
                    "native_attack_events": list(native_attack_events),
                    "schema_version": TELEMETRY_SCHEMA_VERSION,
                    "run_id": telemetry_run_id,
                    "book": attack.book,
                    "chapter": attack.chapter,
                    "stage": attack.state.stage,
                    "enemy": attack.state.enemy,
                    "strategy": attack.strategy,
                    "clean": attack.attempts == 1,
                    "action": candidate_payload(attack.candidate),
                    "timing": {
                        "attack_to_zero_health_seconds": (
                            zero_at - attack.attack_sent_at
                        ),
                        "input_attempts": attack.attempts,
                    },
                }
                assert args.telemetry is not None
                args.telemetry.parent.mkdir(parents=True, exist_ok=True)
                with args.telemetry.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(kill_sample, sort_keys=True) + "\n")
                attack.kill_timing_logged = True
                log_message(
                    f"Attack timing {attack.candidate.word}: "
                    "attack_to_zero_health_ms="
                    f"{(zero_at - attack.attack_sent_at) * 1000:.1f}; "
                    f"animation={attack.candidate.animation_class}; "
                    f"gems={','.join(attack.candidate.gem_types) or 'none'}.",
                    flush=True,
                )
            death_flags_event = DEATH_FLAGS_RE.search(line)
            if death_flags_event:
                log_message(
                    "Native death edge: "
                    f"enemy={death_flags_event.group('enemy')}; "
                    f"anims_done={death_flags_event.group('anims_done')}; "
                    f"death_sequence={death_flags_event.group('death_sequence')}; "
                    f"final_sequence={death_flags_event.group('final_sequence')}; "
                    f"interrupt={death_flags_event.group('interrupt')}; "
                    f"boss_state={death_flags_event.group('boss_state')}; "
                    f"checkpoint_state={death_flags_event.group('checkpoint_state')}"
                )
            zero_health_state = (
                attack_state_for_event(
                    attack.state, last_attack_state,
                    zero_health_event.group("enemy"),
                )
                if zero_health_event else None
            )
            if (
                zero_health_event
                and zero_health_event.group("enemy") == "Codex (Final Boss)"
            ):
                log_message(
                    f"Codex reached zero HP after {attacks} automated attacks; "
                    "campaign complete.",
                    flush=True,
                )
                return
            if zero_health_event and tutorial_play_submitted:
                # The scripted PLAY tutorial disables conversation probes while
                # it owns the rack.  Its first post-victory Cassandra overlay
                # is not consistently reported by convpanel.Active(), so the
                # zero-health edge is the reliable point at which generic
                # dialogue recovery can safely resume.
                active_dialog = None
                dialog_probe_at = time.monotonic() + args.dialog_probe_interval
            if (
                zero_health_event and args.auto_menu_reset
                and zero_health_state is not None
                # Zero HP is too early: exiting at this edge can restore the
                # boss's pre-lethal state. Arm the reset here, but wait for the
                # engine's confirmed save-ready event. Route checkpoints still
                # use DEFEATED.
                and should_arm_boss_reset_on_zero_health(zero_health_state)
                and encounter_key(zero_health_state) not in reset_encounters
                and boss_reset_state is None
            ):
                log_message(
                    f"Lua confirmed {zero_health_event.group('enemy')} reached zero HP; "
                    "waiting for the Lua-confirmed save-ready edge.",
                    flush=True,
                )
                boss_reset_state = zero_health_state
                dialog_probe_at = float("inf")
            reset_ready_event = RESET_READY_RE.search(line)
            if reset_ready_event and boss_reset_state is not None:
                last_boss_reset_key = encounter_key(boss_reset_state)
                last_boss_reset_sequence = max(boss_reset_state.sequence, stream_ready_sequence)
                reset_encounters.add(last_boss_reset_key)
                log_message(
                    f"Lua confirmed {reset_ready_event.group('enemy')} death animation "
                    "settled before the result interrupt; immediate reset "
                    "through the main menu.",
                    flush=True,
                )
                reset_from_battle(
                    controller, RESET_MENU_TIMING, telemetry_log=args.log, trace=menu_trace,
                )
                boss_reset_state = None
                boss_reset_dialog_ready = False
                menu_reentry_pending = True
                menu_reentry_attempts = 0
                menu_reentry_dialog_clicks = 0
                menu_reentry_at = (
                    time.monotonic() + MENU_REENTRY_RETRY_SECONDS
                )
                attack.sequence = (
                    deluxe_state.sequence if deluxe_state is not None else None
                )
                attack.acknowledged = True
                attack.retry_at = float("inf")
                ready = False
                deadline = time.monotonic() + args.timeout
            defeated_event = DEFEATED_RE.search(line)
            if defeated_event:
                pending_health_potion_state = None
                pending_health_potion_at = float("inf")
                pending_health_potion_attempts = 0
            if (
                defeated_event and args.auto_menu_reset
                and boss_reset_state is None
            ):
                defeated_state = attack_state_for_event(
                    attack.state, last_attack_state,
                    defeated_event.group("enemy"),
                )
                reset_reason = immediate_defeated_reset_reason(
                    defeated_state, defeated_event.group("enemy"),
                    reset_encounters, chapter,
                )
                if reset_reason is not None:
                    assert defeated_state is not None
                    reset_encounters.add(encounter_key(defeated_state))
                    log_message(
                        f"Lua confirmed {defeated_event.group('enemy')} defeated; "
                        f"menu reset {reset_reason}.",
                        flush=True,
                    )
                    reset_from_battle(
                        controller, RESET_MENU_TIMING, telemetry_log=args.log, trace=menu_trace,
                    )
                    # An ambient Lex line on the main menu can consume the
                    # Adventure click. Retry it until combat telemetry proves
                    # that re-entry completed.
                    menu_reentry_pending = True
                    menu_reentry_attempts = 0
                    menu_reentry_dialog_clicks = 0
                    menu_reentry_at = (
                        time.monotonic() + MENU_REENTRY_RETRY_SECONDS
                    )
                    attack.sequence = (
                        deluxe_state.sequence if deluxe_state is not None else None
                    )
                    attack.acknowledged = True
                    attack.retry_at = float("inf")
                    ready = False
                    deadline = time.monotonic() + args.timeout
            if args.layout == "deluxe":
                state_buffer = (state_buffer + "\n" + line)[-32768:]
            new_state = parse_state(state_buffer) if args.layout == "deluxe" else None
            if new_state is not None and (
                deluxe_state is None or new_state.sequence >= deluxe_state.sequence
            ):
                if deluxe_state is None or new_state.sequence > deluxe_state.sequence:
                    # A fresh combat state is also definitive proof that the
                    # prompt was accepted, even if its callback was omitted.
                    pending_minigame_prompt = None
                    minigame_prompt_retry_at = float("inf")
                if pending_health_potion_state is not None and health_potion_confirmed(
                    pending_health_potion_state, new_state
                ):
                    log_message(
                        "Native health-potion consumption confirmed: "
                        f"HP {pending_health_potion_state.player_hp:g} -> "
                        f"{new_state.player_hp:g}; potion_available="
                        f"{int(new_state.health_potion_available)}.",
                        flush=True,
                    )
                    pending_health_potion_state = None
                    pending_health_potion_at = float("inf")
                    pending_health_potion_attempts = 0
                new_key = encounter_key(new_state)
                if (
                    last_boss_reset_key == new_key
                    and boss_replay_is_fresh(new_state, last_boss_reset_sequence)
                ):
                    # Re-entering the same full-health boss means the exit beat
                    # the save commit. Allow one replay instead of deadlocking
                    # behind the at-most-once reset and unchanged-state guards.
                    log_message(
                        f"Boss reset replayed {new_state.enemy}; clearing reset guard.",
                        flush=True,
                    )
                    reset_encounters.discard(new_key)
                    last_boss_reset_key = None
                    last_boss_reset_sequence = None
                    attack.state = None
                    attack.sequence = None
                deluxe_state = new_state
                board = new_state.board
                if completes_early_ready(new_state, early_ready_board):
                    ready = True
                    ready_at = time.monotonic() + args.ready_delay
                    early_ready_board = None
                    log_message(
                        f"Complete state {new_state.sequence} recovered for "
                        "early READY event.",
                        flush=True,
                    )
            match = CHAPTER_RE.search(line)
            if match:
                if chapter_enter_attempts and attack.state is not None:
                    map_enter_encounters.add(encounter_key(attack.state))
                chapter = int(match.group("chapter"))
                # A board can be published before the native start-game
                # callback has finished handing mouse ownership to combat.
                # Keep a menu re-entry armed until CHAPTER_ACTION confirms
                # start-game; otherwise the first rack click is consistently
                # dropped after the every-enemy main-menu skip.
                chapter_enter_pending = False
                chapter_enter_at = float("inf")
                attack.board = None
                ready = False
                log_message(f"Entered Chapter {chapter}.", flush=True)
            for event in BOARD_EVENT_RE.finditer(line):
                if chapter_enter_attempts and attack.state is not None:
                    map_enter_encounters.add(encounter_key(attack.state))
                board = event.group("board")
                if args.layout == "deluxe" and event.group("kind") == "BOARD":
                    # BOARD is emitted during refill, before the death/menu
                    # sequence. Only rack legality is cached: READY still owns
                    # input and all HP, treasure, gem and tile-state scoring.
                    if rack_prefetch.prepare(board, deluxe_words, attack.state):
                        LOGGER.debug("Prefetched %d words for early rack %s.",
                                     len(rack_prefetch.words), board)
                if (
                    not tutorial_play_submitted
                    and is_initial_play_tutorial(
                        board, active_dialog, deluxe_state, attacks
                    )
                ):
                    tutorial_play_submitted = True
                    log_message("Completing fixed fresh-profile PLAY tutorial.", flush=True)
                    deadline = time.monotonic() + args.timeout
                menu_reentry_pending = False
                menu_reentry_at = float("inf")
                chapter_enter_pending = False
                chapter_enter_at = float("inf")
                # A transition also proves that Attack was accepted if Wine
                # happened to mangle the acknowledgement line in the console.
                if event.group("kind") == "BOARD" and not attack.acknowledged:
                    attack.acknowledged = True
                    attack.retry_at = float("inf")
                    if attacks >= args.max_attacks:
                        raise RuntimeError(
                            f"Stopped after the safety limit of {args.max_attacks} attacks"
                        )
                if event.group("kind") == "READY":
                    if blocked_screen == "treasure" or treasure_selection_started:
                        blocked_screen, treasure_selection_started = (
                            clear_stale_treasure_on_ready(
                                blocked_screen, treasure_selection_started
                            )
                        )
                        log_message(
                            "Native combat READY superseded stale treasure "
                            "transition; input and dialogue pulses rearmed.",
                            flush=True,
                        )
                    ready_sequence = stream_ready_sequence
                    if not ready_sequence_is_fresh(
                        ready_sequence, required_ready_after_overlay,
                    ):
                        ready = False
                        log_message(
                            f"Ignoring stale READY sequence {ready_sequence}; "
                            "an overlay owned the previous rack state.", flush=True,
                        )
                        continue
                    if required_ready_after_overlay is not None:
                        log_message(
                            f"Fresh READY sequence {ready_sequence} confirmed "
                            "after overlay exit; rack input rearmed.", flush=True,
                        )
                        required_ready_after_overlay = None
                    if menu_trace:
                        menu_trace.event('battle_ready_observed', sequence=ready_sequence)
                    dialog_probe_at = float("inf")
                    dialog_probe_count = 0
                    if (
                        args.layout == "deluxe" and attack.started_at is not None
                        and attack.candidate is not None and attack.state is not None
                        and deluxe_state is not None
                    ):
                        sample = {
                            "schema_version": TELEMETRY_SCHEMA_VERSION,
                            "native_attack_events": list(native_attack_events),
                            "run_id": telemetry_run_id,
                            "book": attack.book,
                            "chapter": attack.chapter,
                            "stage": attack.state.stage,
                            "clean": attack.attempts == 1,
                            "issues": (
                                [] if attack.attempts == 1
                                else [f"input-attempts:{attack.attempts}"]
                            ),
                            "strategy": attack.strategy,
                            "state_fingerprint": state_fingerprint(attack.state),
                            "before": state_payload(attack.state),
                            "action": candidate_payload(attack.candidate),
                            "frontier": [
                                candidate_payload(candidate)
                                for candidate in pareto_candidates(
                                    attack.frontier
                                )
                            ],
                            "after": state_payload(deluxe_state),
                            "timing": {
                                "ready_seconds": time.monotonic() - attack.started_at,
                                "input_seconds": (
                                    attack.attack_sent_at - attack.started_at
                                    if attack.attack_sent_at is not None else None
                                ),
                                "resolution_seconds": (
                                    time.monotonic() - attack.attack_sent_at
                                    if attack.attack_sent_at is not None else None
                                ),
                                "input_attempts": attack.attempts,
                            },
                            # Flat v1-compatible fields remain during migration.
                            "sequence": attack.state.sequence,
                            "enemy": attack.state.enemy,
                            "hp": attack.state.hp,
                            "word": attack.candidate.word,
                            "letters": len(attack.candidate.word),
                            "damage": attack.candidate.damage,
                            "overkill": attack.candidate.overkill,
                            "tier": attack.candidate.tier,
                            "gems_used": attack.candidate.gem_count,
                            "gem_types_used": list(attack.candidate.gem_types),
                            "uses_diamond": (
                                "diamond" in attack.candidate.gem_types
                            ),
                            "attack_animation_class": (
                                attack.candidate.animation_class
                            ),
                            "predicted_seconds": attack.candidate.predicted_time,
                            "actual_seconds": time.monotonic() - attack.started_at,
                            "next_sequence": deluxe_state.sequence,
                            "next_enemy": deluxe_state.enemy,
                            "next_hp": deluxe_state.hp,
                            "enemy_defeated": deluxe_state.enemy != attack.state.enemy,
                            "observed_damage": (
                                attack.state.hp - deluxe_state.hp
                                if deluxe_state.enemy == attack.state.enemy else None
                            ),
                        }
                        assert args.telemetry is not None
                        args.telemetry.parent.mkdir(parents=True, exist_ok=True)
                        with args.telemetry.open("a", encoding="utf-8") as output:
                            output.write(json.dumps(sample, sort_keys=True) + "\n")
                        attack.started_at = None
                        attack.attack_sent_at = None
                        attack.strategy = None
                        attack.frontier = []
                    ready = True
                    ready_at = time.monotonic() + args.ready_delay
                    log_message(f"Board ready: {board}", flush=True)
                else:
                    dialog_probe_at = time.monotonic() + args.dialog_stall_delay
                    dialog_probe_count = 0
                    log_message(f"Board update: {board}", flush=True)
            if DONE_MARKER in line:
                label = f"Chapter {chapter}" if chapter is not None else "Chapter"
                log_message(f"{label} complete after {attacks} automated attacks.", flush=True)
                return


def main() -> None:
    """Compatibility entry point; the readable application lives in tas.py."""
    from tas import main as run_tas
    run_tas()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, RuntimeError, TimeoutError) as error:
        log_message(f"continuous runner stopped: {error}", file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        LOGGER.exception("continuous runner crashed with an unexpected exception")
        raise
