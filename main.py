"""Gamepad Mapper entry point: ``python main.py`` (or ``pythonw main.py`` without a console)."""

from __future__ import annotations

import os
import sys

APP_TITLE = "Gamepad Mapper"
_MUTEX_NAME = "Local\\GamepadMapper.SingleInstance"
_ERROR_ALREADY_EXISTS = 183
_instance_handle = None  # keeps the single-instance mutex alive for the process lifetime


def _notify(text: str) -> None:
    """Show a message even when started with pythonw (no console)."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, APP_TITLE, 0x40)
    else:
        print(text, file=sys.stderr)


def _already_running() -> bool:
    """Two instances would inject every input twice, so only one may run."""
    global _instance_handle
    if sys.platform != "win32":
        return False
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _instance_handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    return ctypes.get_last_error() == _ERROR_ALREADY_EXISTS


def main() -> int:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    # Keep receiving controller input while another application has focus.
    os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
    # SDL's video init would otherwise block the screensaver and display sleep.
    os.environ.setdefault("SDL_VIDEO_ALLOW_SCREENSAVER", "1")
    if _already_running():
        _notify(f"{APP_TITLE} is already running. Look for its icon in the system tray.")
        return 0
    try:
        from app.ui.app_window import run
    except ImportError as exc:
        _notify(f"A dependency is missing ({exc.name}).\n\nRun: pip install -r requirements.txt")
        return 1
    return run()


if __name__ == "__main__":
    sys.exit(main())
