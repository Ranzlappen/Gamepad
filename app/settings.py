"""User settings persisted in settings.json beside the entry point."""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from app import paths
from app.logging_setup import log
from app.model import DEFAULT_ANTI_DRIFT, DEFAULT_DEADZONE, as_float, clamp

POLLING_RATES = (125, 250, 500, 1000)
THEMES = ("dark", "light")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = paths.APP_ID


@dataclass
class Settings:
    polling_hz: int = 250
    default_deadzone: float = DEFAULT_DEADZONE
    default_anti_drift: float = DEFAULT_ANTI_DRIFT
    mouse_sensitivity: float = 1.0
    start_with_windows: bool = False
    start_minimized: bool = False
    close_to_tray: bool = True
    theme: str = "dark"
    debug_logging: bool = False
    active_profile: str = ""
    first_run_done: bool = False
    # Per-controller raw-input layouts keyed by SDL GUID: {"preset": ..., "bindings": {...}}.
    layouts: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or paths.settings_path()
        settings = cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return settings
        except (OSError, ValueError):
            log.warning("settings.json is unreadable; using defaults", exc_info=True)
            return settings
        if isinstance(raw, dict):
            for f in fields(cls):
                if f.name in raw:
                    setattr(settings, f.name, raw[f.name])
        settings.sanitize()
        return settings

    def sanitize(self) -> None:
        d = Settings()
        hz = int(as_float(self.polling_hz, d.polling_hz))
        self.polling_hz = hz if hz in POLLING_RATES else d.polling_hz
        self.default_deadzone = clamp(as_float(self.default_deadzone, d.default_deadzone), 0.0, 0.9)
        self.default_anti_drift = clamp(as_float(self.default_anti_drift, d.default_anti_drift), 0.0, 0.5)
        self.mouse_sensitivity = clamp(as_float(self.mouse_sensitivity, 1.0), 0.1, 10.0)
        for name in ("start_with_windows", "start_minimized", "close_to_tray",
                     "debug_logging", "first_run_done"):
            setattr(self, name, bool(getattr(self, name)))
        self.theme = self.theme if self.theme in THEMES else d.theme
        self.active_profile = self.active_profile if isinstance(self.active_profile, str) else ""
        self.layouts = self.layouts if isinstance(self.layouts, dict) else {}

    def save(self, path: Path | None = None) -> None:
        try:
            paths.atomic_write_text(path or paths.settings_path(), json.dumps(asdict(self), indent=2))
        except OSError:
            log.warning("Could not save settings.json", exc_info=True)


# --- start with Windows (HKCU Run key) --------------------------------------

def launch_command() -> str:
    """Command line stored in the Run key (pythonw.exe avoids a console window)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    return f'"{interpreter}" "{paths.app_dir() / "main.py"}"'


def set_start_with_windows(enabled: bool) -> bool:
    """Create or remove the Run value. Returns True on success."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, RUN_VALUE)
        return True
    except OSError:
        log.warning("Could not update the Windows Run key", exc_info=True)
        return False


def is_start_with_windows() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
        return True
    except OSError:
        return False
