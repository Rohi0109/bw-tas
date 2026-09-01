"""Book 1 transition corpus and bounded lookahead utilities.

The native game owns rack generation.  This module deliberately treats a
recorded before/action/after tuple as the transition oracle until every native
letter-generation rule has been reproduced and validated.  Unknown branches
are never guessed by the live runner.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from deluxe_optimizer import Candidate, DeluxeState


TELEMETRY_SCHEMA_VERSION = 2


def state_payload(state: DeluxeState) -> dict:
    payload = asdict(state)
    payload["gems"] = list(state.gems)
    payload["tile_powers"] = list(state.tile_powers)
    payload["treasures"] = sorted(state.treasures)
    payload["overkill_thresholds"] = list(state.overkill_thresholds)
    payload["selectable"] = list(state.selectable)
    payload["zero_damage"] = list(state.zero_damage)
    return payload


def state_from_payload(payload: dict) -> DeluxeState:
    values = dict(payload)
    values["gems"] = tuple(values["gems"])
    values["tile_powers"] = tuple(values["tile_powers"])
    values["treasures"] = frozenset(values["treasures"])
    values["overkill_thresholds"] = tuple(values["overkill_thresholds"])
    values["selectable"] = tuple(values.get("selectable", (True,) * 16))
    values["zero_damage"] = tuple(values.get("zero_damage", (False,) * 16))
    return DeluxeState(**values)


def candidate_payload(candidate: Candidate) -> dict:
    payload = asdict(candidate)
    payload["path"] = list(candidate.path)
    return payload


def state_fingerprint(state: DeluxeState) -> str:
    """Stable identity for a decision state, excluding the log sequence."""
    payload = state_payload(state)
    payload.pop("sequence", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:20]


def action_key(word: str, path: Iterable[int]) -> str:
    return f"{word.upper()}:{','.join(str(index) for index in path)}"


def preserved_tiles(
    before: DeluxeState, after: DeluxeState, path: Iterable[int],
) -> tuple[int, ...]:
    """Return unselected indexes whose letter and gem survived a transition."""
    used = set(path)
    before_letters = before.board.replace("/", "")
    after_letters = after.board.replace("/", "")
    return tuple(
        index for index in range(16)
        if index not in used
        and before_letters[index] == after_letters[index]
        and before.gems[index] == after.gems[index]
    )


def replacement_letters(
    before: DeluxeState, after: DeluxeState, path: Iterable[int],
) -> tuple[str, ...]:
    """Extract native replacement results in selected-path order."""
    after_letters = after.board.replace("/", "")
    return tuple(after_letters[index] for index in path)


def transition_errors(
    before: DeluxeState, candidate: Candidate, after: DeluxeState,
) -> list[str]:
    """Validate invariants needed by the rack transition model."""
    errors: list[str] = []
    if before.book != 1 or not 1 <= before.chapter <= 5:
        errors.append("transition is outside Book 1 Chapters 1-5")
    used = set(candidate.path)
    if len(used) != len(candidate.path):
        errors.append("candidate path reuses a tile")
    if candidate.word != "".join(
        before.board.replace("/", "")[index] for index in candidate.path
    ):
        errors.append("candidate path does not spell its word")
    # During ordinary early-book combat, tiles not used in the word must carry
    # forward. Enemy tile effects are represented by selectable/zero_damage and
    # may legitimately alter attributes, but not the underlying letter.
    before_letters = before.board.replace("/", "")
    after_letters = after.board.replace("/", "")
    for index in range(16):
        if index not in used and before_letters[index] != after_letters[index]:
            errors.append(f"unselected tile {index} changed letter")
    if before.enemy == after.enemy and after.hp > before.hp + 1.0:
        errors.append("enemy gained more than the known one-heart regeneration")
    if (
        before.rng_calls >= 0 and after.rng_calls >= 0
        and after.rng_calls < before.rng_calls
    ):
        errors.append("relative RNG cursor moved backwards")
    return errors


@dataclass(frozen=True)
class RecordedTransition:
    before: DeluxeState
    candidate: Candidate
    after: DeluxeState
    elapsed: float
    clean: bool


class TransitionCorpus:
    def __init__(self, transitions: Iterable[RecordedTransition] = ()):
        self._by_action: dict[tuple[str, str], RecordedTransition] = {}
        for transition in transitions:
            if transition.clean and not transition_errors(
                transition.before, transition.candidate, transition.after
            ):
                key = (
                    state_fingerprint(transition.before),
                    action_key(transition.candidate.word, transition.candidate.path),
                )
                current = self._by_action.get(key)
                if current is None or transition.elapsed < current.elapsed:
                    self._by_action[key] = transition

    @classmethod
    def load(cls, path: Path) -> "TransitionCorpus":
        transitions = []
        if not path.exists():
            return cls()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                if row.get("schema_version") != TELEMETRY_SCHEMA_VERSION:
                    continue
                action = row["action"]
                candidate = Candidate(
                    word=action["word"], path=tuple(action["path"]),
                    damage=action["damage"], overkill=action["overkill"],
                    tier=action.get("tier"), lethal=action["lethal"],
                    predicted_time=action["predicted_time"],
                    gem_count=action["gem_count"],
                )
                transitions.append(RecordedTransition(
                    state_from_payload(row["before"]), candidate,
                    state_from_payload(row["after"]),
                    float(row["timing"]["ready_seconds"]),
                    bool(row.get("clean", False)),
                ))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return cls(transitions)

    def successor(
        self, state: DeluxeState, candidate: Candidate,
    ) -> RecordedTransition | None:
        return self._by_action.get((
            state_fingerprint(state), action_key(candidate.word, candidate.path)
        ))

    def known_actions(self, state: DeluxeState) -> int:
        fingerprint = state_fingerprint(state)
        return sum(key[0] == fingerprint for key in self._by_action)


def pareto_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Drop candidates worse in damage, input time, and selected tile set."""
    best: dict[frozenset[int], Candidate] = {}
    for candidate in candidates:
        mask = frozenset(candidate.path)
        incumbent = best.get(mask)
        if incumbent is None or (
            candidate.damage > incumbent.damage
            or (
                candidate.damage == incumbent.damage
                and candidate.predicted_time < incumbent.predicted_time
            )
        ):
            best[mask] = candidate
    values = list(best.values())
    return [
        candidate for candidate in values
        if not any(
            other is not candidate
            and other.damage >= candidate.damage
            and other.predicted_time <= candidate.predicted_time
            and frozenset(other.path) == frozenset(candidate.path)
            for other in values
        )
    ]


def choose_recorded_lookahead(
    state: DeluxeState, candidates: Iterable[Candidate], corpus: TransitionCorpus,
) -> Candidate | None:
    """Choose the fastest validated successor; require competing branches.

    Returning ``None`` is intentional: one recorded action is a replay, not a
    comparison, and must not override the established live policy.
    """
    known = [
        (candidate, corpus.successor(state, candidate))
        for candidate in pareto_candidates(candidates)
    ]
    known = [(candidate, edge) for candidate, edge in known if edge is not None]
    if len(known) < 2:
        return None
    return min(known, key=lambda item: (item[1].elapsed, item[0].predicted_time))[0]
