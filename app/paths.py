"""Filesystem locations used by the app."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Gamepad Mapper"
APP_ID = "GamepadMapper"


def app_dir() -> Path:
    """Directory that holds main.py (or the frozen executable)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def settings_path() -> Path:
    return app_dir() / "settings.json"


def profiles_dir() -> Path:
    return app_dir() / "profiles"


def log_dir() -> Path:
    """Rotating debug log location: %APPDATA%\\GamepadMapper\\logs."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_ID / "logs"


def atomic_write_text(path: Path, text: str) -> None:
    """Write through a temp file and os.replace so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
