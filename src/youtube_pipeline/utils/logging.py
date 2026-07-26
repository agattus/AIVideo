"""Structured logging helpers with clear pipeline stage banners."""

from __future__ import annotations

import logging
import sys


_STAGE_TOTAL = 3


def setup_logging(level: str = "INFO", *, force: bool = False) -> None:
    """Configure root logging once for CLI / orchestrator entrypoints."""
    root = logging.getLogger()
    if root.handlers and not force:
        root.setLevel(level.upper())
        return

    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)

    # Prefer UTF-8 on Windows so accidental non-ASCII log text does not crash,
    # while project log messages themselves stay ASCII-safe.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Keep noisy third-party loggers quieter during a local render.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("moviepy").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_stage(logger: logging.Logger, stage: int, message: str, *, total: int = _STAGE_TOTAL) -> None:
    """Emit a high-visibility pipeline stage line.

    Example::

        [INFO] Stage 1/5: Generating Script via OpenAI Structured Outputs...
    """
    logger.info("Stage %d/%d: %s", stage, total, message)
