"""Logging: warnings to stderr, plus an opt-in rotating debug log under AppData."""

from __future__ import annotations

import logging
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

from app import paths

log = logging.getLogger("gamepad")

_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s"
_LOG_FILE = "gamepad-mapper.log"
_MAX_BYTES = 1_000_000
_BACKUPS = 3

_lock = threading.Lock()
_file_handler: RotatingFileHandler | None = None
_last_emit: dict[str, float] = {}


def configure(debug: bool) -> None:
    """Install the stderr handler once and apply the debug-log setting."""
    log.propagate = False
    if sys.stderr is not None and not log.handlers:
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(logging.WARNING)
        stream.setFormatter(logging.Formatter(_FORMAT))
        log.addHandler(stream)
    set_debug(debug)


def set_debug(enabled: bool) -> None:
    """Attach or detach the rotating file handler (safe to call at any time)."""
    global _file_handler
    with _lock:
        if enabled and _file_handler is None:
            try:
                directory = paths.log_dir()
                directory.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(
                    directory / _LOG_FILE,
                    maxBytes=_MAX_BYTES,
                    backupCount=_BACKUPS,
                    encoding="utf-8",
                )
            except OSError:
                log.warning("Could not open the debug log", exc_info=True)
                return
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter(_FORMAT))
            log.addHandler(handler)
            _file_handler = handler
        elif not enabled and _file_handler is not None:
            log.removeHandler(_file_handler)
            _file_handler.close()
            _file_handler = None
        # Keep the hot mapping loop cheap when nobody reads debug records.
        log.setLevel(logging.DEBUG if _file_handler is not None else logging.WARNING)
    if enabled:
        log.info("Debug logging enabled: %s", paths.log_dir() / _LOG_FILE)


def debug_throttled(key: str, interval_s: float, msg: str, *args: object) -> None:
    """Debug-log at most once per interval per key (for per-tick events such as jitter)."""
    if not log.isEnabledFor(logging.DEBUG):
        return
    now = time.monotonic()
    if now - _last_emit.get(key, -interval_s) >= interval_s:
        _last_emit[key] = now
        log.debug(msg, *args)
