from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from threading import Lock
from typing import Any

from .paths import app_data_dir

_logger: logging.Logger | None = None
_lock = Lock()


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    with _lock:
        if _logger is not None:
            return _logger
        log_dir = app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("transcriptor.engine")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            handler = RotatingFileHandler(
                log_dir / "engine.log",
                maxBytes=1_000_000,
                backupCount=2,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            logger.addHandler(handler)
        _logger = logger
        return logger


def record_diagnostic(event: str, **fields: Any) -> None:
    """Write privacy-safe engine metadata; callers must never pass paths or transcript text."""
    try:
        payload = {"event": event, **fields}
        _get_logger().info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    except OSError:
        # Diagnostics must never prevent a local transcription from running.
        return
