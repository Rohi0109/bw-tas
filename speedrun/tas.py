"""The TAS in plain English. Detailed game coordination lives in continuous_runner."""

from contextlib import contextmanager
import sys

import continuous_runner as game
from tas_settings import read_settings


@contextmanager
def claim_exclusive_control(settings):
    """Keep other runners out until this run exits, including on startup errors."""
    lock_path = settings.log.resolve().parent.parent / "diagnostics" / "tas-runner.lock"
    lock = game.acquire_runner_lock(lock_path)
    try:
        yield
    finally:
        lock.close()


def main() -> None:
    settings = read_settings()
    game.configure_logging(settings.log_level, settings.log_file)

    with claim_exclusive_control(settings):
        session = game.prepare_game(settings)
        game.follow_game_until_finished(session)


def run_from_terminal() -> None:
    try:
        main()
    except (KeyboardInterrupt, RuntimeError, TimeoutError) as error:
        game.log_message(f"continuous runner stopped: {error}", file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        game.LOGGER.exception("continuous runner crashed with an unexpected exception")
        raise


if __name__ == "__main__":
    run_from_terminal()
