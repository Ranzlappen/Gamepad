"""Synthetic keyboard and mouse output with per-owner bookkeeping.

Every held key or mouse button records which owners hold it. An owner is a
``(device_instance_id, slot_id)`` tuple, or ``("tap", n)`` for short taps.
A key goes down when its first owner presses it and up only when its last
owner releases it, so overlapping mappings never release each other's keys,
and ``release_owners()`` / ``release_all()`` can always clean up completely.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable

from app import keys
from app.logging_setup import log

Owner = tuple


class PynputBackend:
    """Keyboard and mouse buttons through pynput; relative motion through SendInput."""

    def __init__(self) -> None:
        from pynput import keyboard, mouse

        self._keyboard = keyboard.Controller()
        self._mouse = mouse.Controller()
        self._key_enum = keyboard.Key
        self._key_code = keyboard.KeyCode
        self._button_enum = mouse.Button
        self._cache: dict[str, object] = {}
        self._relative = _win32_relative_mover() if sys.platform == "win32" else None

    def _resolve(self, name: str) -> object:
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        if name in keys.PYNPUT_KEY_NAMES and hasattr(self._key_enum, name):
            resolved = getattr(self._key_enum, name)
        elif sys.platform == "win32" and name in keys.VK_BY_NAME:
            resolved = self._key_code.from_vk(keys.VK_BY_NAME[name])
        elif len(name) == 1:
            resolved = self._key_code.from_char(name)
        elif name.startswith("num") and name[3:].isdigit():
            resolved = self._key_code.from_char(name[3:])
        else:
            raise ValueError(f"Key '{name}' is not available on this platform")
        self._cache[name] = resolved
        return resolved

    def key(self, name: str, down: bool) -> None:
        key = self._resolve(name)
        if down:
            self._keyboard.press(key)
        else:
            self._keyboard.release(key)

    def button(self, name: str, down: bool) -> None:
        button = getattr(self._button_enum, name, self._button_enum.left)
        if down:
            self._mouse.press(button)
        else:
            self._mouse.release(button)

    def move(self, dx: int, dy: int) -> None:
        if self._relative is not None:
            self._relative(dx, dy)
        else:
            self._mouse.move(dx, dy)


def _win32_relative_mover() -> Callable[[int, int], None]:
    """Relative SendInput mouse motion.

    pynput moves the cursor with SetCursorPos, which games that read raw
    mouse input (mouse look) never see; MOUSEEVENTF_MOVE produces real deltas.
    """
    import ctypes
    from ctypes import wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t))

    class _INPUTUNION(ctypes.Union):
        _fields_ = (("mi", MOUSEINPUT),)

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))

    input_mouse, mouseeventf_move = 0, 0x0001
    send_input = ctypes.WinDLL("user32", use_last_error=True).SendInput
    send_input.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    send_input.restype = wintypes.UINT

    def move(dx: int, dy: int) -> None:
        event = INPUT(type=input_mouse, mi=MOUSEINPUT(dx, dy, 0, mouseeventf_move, 0, 0))
        send_input(1, ctypes.byref(event), ctypes.sizeof(INPUT))

    return move


class Injector:
    def __init__(self, backend: object | None = None) -> None:
        self._backend = backend if backend is not None else PynputBackend()
        self._keys: dict[str, set[Owner]] = {}
        self._buttons: dict[str, set[Owner]] = {}
        self._lock = threading.RLock()

    # --- keyboard --------------------------------------------------------------

    def press_keys(self, owner: Owner, names: list[str], retrigger: bool = False) -> None:
        with self._lock:
            for name in names:
                self._press(self._keys, name, owner, retrigger, self._send_key)

    def release_keys(self, owner: Owner, names: list[str]) -> None:
        with self._lock:
            for name in reversed(names):  # modifiers last: ctrl+c releases c, then ctrl
                self._release(self._keys, name, owner, self._send_key)

    # --- mouse -----------------------------------------------------------------

    def press_button(self, owner: Owner, name: str, retrigger: bool = False) -> None:
        with self._lock:
            self._press(self._buttons, name, owner, retrigger, self._send_button)

    def release_button(self, owner: Owner, name: str) -> None:
        with self._lock:
            self._release(self._buttons, name, owner, self._send_button)

    def move_mouse(self, dx: int, dy: int) -> None:
        if dx or dy:
            try:
                self._backend.move(dx, dy)
            except Exception:  # never let an OS hiccup kill the mapping loop
                log.exception("Mouse move failed")

    # --- cleanup ---------------------------------------------------------------

    def release_owners(self, predicate: Callable[[Owner], bool]) -> list[str]:
        """Release everything held by matching owners; returns what went up."""
        released: list[str] = []
        with self._lock:
            for table, send in ((self._keys, self._send_key), (self._buttons, self._send_button)):
                for name in list(table):
                    owners = table[name]
                    owners.difference_update({o for o in owners if predicate(o)})
                    if not owners:
                        del table[name]
                        send(name, False)
                        released.append(name)
        return released

    def release_all(self) -> list[str]:
        return self.release_owners(lambda _owner: True)

    def held(self) -> list[str]:
        with self._lock:
            return sorted(self._keys) + [f"mouse:{b}" for b in sorted(self._buttons)]

    # --- internals -------------------------------------------------------------

    @staticmethod
    def _press(table: dict, name: str, owner: Owner, retrigger: bool, send: Callable) -> None:
        owners = table.setdefault(name, set())
        if not owners:
            send(name, True)
        elif retrigger and all(o[0] == "tap" for o in owners):
            # Two quick taps of one key: end the first tap early so the
            # application sees two separate presses instead of one.
            send(name, False)
            send(name, True)
        else:
            # Edge case (Windows key repeat): the key is already down for another
            # mapping. Synthetic keys never auto-repeat and we never re-send a
            # key-down, so a held key yields exactly one WM_KEYDOWN; re-sending
            # would look like typematic repeat (doubled letters in text fields).
            log.debug("'%s' already held by %s; %s joins without a new key-down",
                      name, sorted(map(str, owners)), owner)
        owners.add(owner)

    @staticmethod
    def _release(table: dict, name: str, owner: Owner, send: Callable) -> None:
        owners = table.get(name)
        if not owners or owner not in owners:
            return
        owners.discard(owner)
        if not owners:
            del table[name]
            send(name, False)

    def _send_key(self, name: str, down: bool) -> None:
        try:
            self._backend.key(name, down)
        except Exception:
            log.exception("Could not send key %s (%s)", name, "down" if down else "up")

    def _send_button(self, name: str, down: bool) -> None:
        try:
            self._backend.button(name, down)
        except Exception:
            log.exception("Could not send mouse button %s (%s)", name, "down" if down else "up")
