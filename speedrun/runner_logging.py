"""Shared runner logging; no game input or policy."""

import logging
import sys
from pathlib import Path

LOGGER = logging.getLogger("bookworm.tas")


def configure_logging(level: str, log_file: Path | None) -> None:
    """Keep concise progress on stdout and detailed diagnostics on disk."""
    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, level))
    console.setFormatter(formatter)
    LOGGER.addHandler(console)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        detailed = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        detailed.setLevel(logging.DEBUG)
        detailed.setFormatter(formatter)
        LOGGER.addHandler(detailed)


def log_message(*values: object, sep: str = " ", end: str = "\n",
                file: object | None = None, flush: bool = False) -> None:
    """Compatibility formatter while routing all runner output through logging."""
    del end, flush
    message = sep.join(str(value) for value in values)
    if file is sys.stderr:
        LOGGER.error(message)
    elif message.startswith((
        "Lua dialogue pulse ", "Ignoring unchanged READY ", "Attack timing ",
    )):
        LOGGER.debug(message)
    elif message.startswith(("No READY event ", "Board ready: ", "Board update: ")):
        LOGGER.debug(message)
    elif " warning:" in message.casefold() or message.startswith("No ATTACK acknowledgement"):
        LOGGER.warning(message)
    else:
        LOGGER.info(message)

