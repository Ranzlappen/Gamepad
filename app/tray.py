"""System-tray icon (pystray): Show/Hide, Pause/Resume, profiles, folder and Exit.

pystray runs its own message loop on a background thread. Menu callbacks
never touch Tk directly; they call the handlers passed in, which the main
window wraps so the work is queued onto the Tk thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from app import paths
from app.logging_setup import log


@dataclass
class TrayHandlers:
    toggle_window: Callable[[], None]
    toggle_pause: Callable[[], None]
    select_profile: Callable[[str], None]
    open_profiles_folder: Callable[[], None]
    exit_app: Callable[[], None]


@dataclass
class _TrayState:
    paused: bool = False       # injection actually paused (icon)
    user_paused: bool = False  # the Pause/Resume toggle (menu text)
    profiles: list[str] = field(default_factory=list)
    active: str = ""


def make_icon(paused: bool, size: int = 64) -> Image.Image:
    """A small controller glyph with a green (active) or orange pause badge."""
    s = size / 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    body, light = (88, 96, 110, 255), (225, 230, 235, 255)
    draw.rounded_rectangle((4 * s, 22 * s, 60 * s, 48 * s), radius=12 * s, fill=body)
    draw.ellipse((2 * s, 30 * s, 24 * s, 58 * s), fill=body)
    draw.ellipse((40 * s, 30 * s, 62 * s, 58 * s), fill=body)
    draw.rectangle((13 * s, 29 * s, 17 * s, 41 * s), fill=light)   # d-pad
    draw.rectangle((9 * s, 33 * s, 21 * s, 37 * s), fill=light)
    for cx, cy in ((47, 30), (53, 35), (41, 35), (47, 40)):          # face buttons
        draw.ellipse(((cx - 2.5) * s, (cy - 2.5) * s, (cx + 2.5) * s, (cy + 2.5) * s), fill=light)
    if paused:
        draw.ellipse((36 * s, 0, 64 * s, 28 * s), fill=(230, 126, 34, 255))
        draw.rectangle((44 * s, 7 * s, 48 * s, 21 * s), fill=(255, 255, 255, 255))
        draw.rectangle((52 * s, 7 * s, 56 * s, 21 * s), fill=(255, 255, 255, 255))
    else:
        draw.ellipse((40 * s, 2 * s, 62 * s, 24 * s), fill=(46, 204, 113, 255))
    return image


class Tray:
    def __init__(self, handlers: TrayHandlers) -> None:
        self._handlers = handlers
        self._state = _TrayState()
        self._icon = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        try:
            import pystray
        except Exception:  # missing backend: the app still works without a tray
            log.warning("System tray unavailable", exc_info=True)
            return False
        h = self._handlers
        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide", lambda: h.toggle_window(), default=True),
            pystray.MenuItem(lambda _item: "Resume mapping" if self._state.user_paused else "Pause mapping",
                             lambda: h.toggle_pause()),
            pystray.MenuItem("Profile", pystray.Menu(self._profile_items)),
            pystray.MenuItem("Open profiles folder", lambda: h.open_profiles_folder()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda: h.exit_app()),
        )
        self._icon = pystray.Icon(paths.APP_ID, make_icon(self._state.paused),
                                  self._title(), menu)
        self._thread = threading.Thread(target=self._icon.run, name="tray", daemon=True)
        self._thread.start()
        return True

    def update(self, paused: bool, user_paused: bool, profiles: list[str], active: str) -> None:
        changed_icon = paused != self._state.paused
        self._state = _TrayState(paused, user_paused, list(profiles), active)
        if self._icon is None:
            return
        try:
            if changed_icon:
                self._icon.icon = make_icon(paused)
            self._icon.title = self._title()
            self._icon.update_menu()
        except Exception:
            log.debug("Tray update failed", exc_info=True)

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                log.debug("Tray stop failed", exc_info=True)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _title(self) -> str:
        state = "paused" if self._state.paused else "active"
        profile = f" - {self._state.active}" if self._state.active else ""
        return f"{paths.APP_NAME} ({state}){profile}"

    def _profile_items(self):
        import pystray

        for name in self._state.profiles:
            yield pystray.MenuItem(
                name,
                self._select_action(name),
                checked=lambda _item, n=name: n == self._state.active,
                radio=True,
            )

    def _select_action(self, name: str) -> Callable[[], None]:
        return lambda: self._handlers.select_profile(name)
