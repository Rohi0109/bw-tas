"""Mutable state for one word submission, separate from navigation and solving.

Native authorization means input was allowed, not that the attack was accepted.
Keep that distinction until an acknowledgement arrives. Overlay cancellation
does not erase the runner's last encounter identity used by death/reset events.
"""

from dataclasses import dataclass, field

from combat_models import Candidate, DeluxeState


@dataclass
class AttackLifecycle:
    board: str | None = None
    sequence: int | None = None
    started_at: float | None = None
    attack_sent_at: float | None = None
    kill_timing_logged: bool = False
    native_authorized: bool = False
    candidate: Candidate | None = None
    state: DeluxeState | None = None
    strategy: str | None = None
    frontier: list[Candidate] = field(default_factory=list)
    book: int | None = None
    chapter: int | None = None
    word: str | None = None
    path: tuple[int, ...] | None = None
    acknowledged: bool = True
    presentation_active: bool = False
    presentation_pending_submit: bool = False
    attempts: int = 0
    retry_at: float = float("inf")

    def begin_submission(self, board: str, word: str, path: tuple[int, ...] | None) -> None:
        """Track a selection; native authorization is set by the input handshake."""
        self.board, self.word, self.path = board, word, path
        self.acknowledged = False
        self.attempts = 1

    def acknowledge(self) -> None:
        """Stop retrying after the native submission acknowledgement."""
        self.acknowledged = True
        self.retry_at = float("inf")

    def retry_is_due(self, now: float, *, input_blocked: bool) -> bool:
        return not self.acknowledged and not input_blocked and now >= self.retry_at

    def discard_interrupted_selection(self) -> None:
        """Match the existing dialogue/incapacitation cancellation edge exactly.

        The caller revokes READY and disables retries first. Historical strategy
        and authorization fields retain their prior values, as before this
        refactor; no new inputs are authorized by this method.
        """
        self.board = None
        self.word = None
        self.path = None
        self.sequence = None
        self.state = None
        self.candidate = None
        self.started_at = None
        self.attack_sent_at = None
        self.acknowledged = True
        self.attempts = 0
