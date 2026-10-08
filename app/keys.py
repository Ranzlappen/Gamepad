"""Key names stored in profiles, chord parsing, and Tk-event-to-name mapping.

Profiles store keys as short lowercase names ("w", "space", "ctrl", "f5",
"num4"). Special names match pynput's ``Key`` members so the injector can
send them with the correct extended-key flags; letters, digits, punctuation
and numpad keys are sent by Windows virtual-key code.
"""

from __future__ import annotations

import string

MODIFIERS = ("ctrl", "ctrl_r", "shift", "shift_r", "alt", "alt_r", "alt_gr", "cmd", "cmd_r")

_FUNCTION_KEYS = tuple(f"f{i}" for i in range(1, 25))

SPECIAL_KEYS = (
    "enter", "esc", "space", "tab", "backspace", "delete", "insert",
    "home", "end", "page_up", "page_down", "up", "down", "left", "right",
    "caps_lock", "num_lock", "scroll_lock", "print_screen", "pause", "menu",
    *_FUNCTION_KEYS,
    "media_play_pause", "media_next", "media_previous", "media_stop",
    "media_volume_up", "media_volume_down", "media_volume_mute",
)

# Names that map 1:1 onto pynput's keyboard.Key members.
PYNPUT_KEY_NAMES = frozenset(MODIFIERS + SPECIAL_KEYS)

# Letters, digits and US-layout punctuation, sent by virtual-key code.
CHAR_VK: dict[str, int] = {c: ord(c.upper()) for c in string.ascii_lowercase}
CHAR_VK.update({d: ord(d) for d in string.digits})
CHAR_VK.update({
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
    "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
})

NUMPAD_VK: dict[str, int] = {f"num{i}": 0x60 + i for i in range(10)}
NUMPAD_VK.update({
    "num_multiply": 0x6A, "num_add": 0x6B, "num_subtract": 0x6D,
    "num_decimal": 0x6E, "num_divide": 0x6F,
})

VK_BY_NAME: dict[str, int] = {**CHAR_VK, **NUMPAD_VK}

ALL_KEYS: tuple[str, ...] = (
    tuple(string.ascii_lowercase)
    + tuple(string.digits)
    + SPECIAL_KEYS
    + MODIFIERS
    + tuple(NUMPAD_VK)
    + tuple(k for k in CHAR_VK if not k.isalnum())
)
_VALID = frozenset(ALL_KEYS)

# Categories for the key list in the UI; together they hold every key exactly once.
KEY_GROUPS: dict[str, tuple[str, ...]] = {
    "Letters": tuple(string.ascii_lowercase),
    "Digits": tuple(string.digits),
    "Function keys": _FUNCTION_KEYS,
    "Navigation and editing": (
        "enter", "esc", "space", "tab", "backspace", "delete", "insert",
        "home", "end", "page_up", "page_down", "up", "down", "left", "right",
    ),
    "Modifiers": MODIFIERS,
    "Numpad": tuple(NUMPAD_VK),
    "Punctuation": tuple(k for k in CHAR_VK if not k.isalnum()),
    "System and media": (
        "caps_lock", "num_lock", "scroll_lock", "print_screen", "pause", "menu",
        "media_play_pause", "media_next", "media_previous", "media_stop",
        "media_volume_up", "media_volume_down", "media_volume_mute",
    ),
}

MOUSE_BUTTONS = ("left", "right", "middle", "x1", "x2")

_DISPLAY = {
    "esc": "Esc", "page_up": "Page Up", "page_down": "Page Down",
    "caps_lock": "Caps Lock", "num_lock": "Num Lock", "scroll_lock": "Scroll Lock",
    "print_screen": "Print Screen", "ctrl": "Ctrl", "ctrl_r": "Right Ctrl",
    "shift": "Shift", "shift_r": "Right Shift", "alt": "Alt", "alt_r": "Right Alt",
    "alt_gr": "AltGr", "cmd": "Win", "cmd_r": "Right Win", "menu": "Menu",
    "num_multiply": "Num *", "num_add": "Num +", "num_subtract": "Num -",
    "num_decimal": "Num .", "num_divide": "Num /",
}

# Windows virtual-key codes (Tk's event.keycode on Windows) for non-character keys.
_VK_SPECIAL: dict[int, str] = {
    0x0D: "enter", 0x1B: "esc", 0x20: "space", 0x09: "tab", 0x08: "backspace",
    0x2E: "delete", 0x2D: "insert", 0x24: "home", 0x23: "end", 0x21: "page_up",
    0x22: "page_down", 0x26: "up", 0x28: "down", 0x25: "left", 0x27: "right",
    0x14: "caps_lock", 0x90: "num_lock", 0x91: "scroll_lock", 0x2C: "print_screen",
    0x13: "pause", 0x5D: "menu", 0x5B: "cmd", 0x5C: "cmd_r",
    0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0xA0: "shift", 0xA1: "shift_r",
    0xA2: "ctrl", 0xA3: "ctrl_r", 0xA4: "alt", 0xA5: "alt_r",
    0xB3: "media_play_pause", 0xB0: "media_next", 0xB1: "media_previous",
    0xB2: "media_stop", 0xAF: "media_volume_up", 0xAE: "media_volume_down",
    0xAD: "media_volume_mute",
}
_VK_SPECIAL.update({0x70 + i: f"f{i + 1}" for i in range(24)})
VK_TO_NAME: dict[int, str] = {**_VK_SPECIAL, **{vk: n for n, vk in VK_BY_NAME.items()}}

# Tk keysyms; used for left/right modifier sides and on non-Windows platforms.
KEYSYM_TO_NAME: dict[str, str] = {
    "Shift_L": "shift", "Shift_R": "shift_r", "Control_L": "ctrl", "Control_R": "ctrl_r",
    "Alt_L": "alt", "Alt_R": "alt_r", "Win_L": "cmd", "Win_R": "cmd_r",
    "Super_L": "cmd", "Super_R": "cmd_r", "Return": "enter", "KP_Enter": "enter",
    "Escape": "esc", "space": "space", "Tab": "tab", "ISO_Left_Tab": "tab",
    "BackSpace": "backspace", "Delete": "delete", "Insert": "insert", "Home": "home",
    "End": "end", "Prior": "page_up", "Next": "page_down", "Up": "up", "Down": "down",
    "Left": "left", "Right": "right", "Caps_Lock": "caps_lock", "Num_Lock": "num_lock",
    "Scroll_Lock": "scroll_lock", "Print": "print_screen", "Pause": "pause",
    "App": "menu", "Menu": "menu", "minus": "-", "equal": "=", "bracketleft": "[",
    "bracketright": "]", "semicolon": ";", "apostrophe": "'", "comma": ",",
    "period": ".", "slash": "/", "backslash": "\\", "grave": "`",
    "KP_Multiply": "num_multiply", "KP_Add": "num_add", "KP_Subtract": "num_subtract",
    "KP_Decimal": "num_decimal", "KP_Divide": "num_divide",
}
KEYSYM_TO_NAME.update({f"KP_{i}": f"num{i}" for i in range(10)})
KEYSYM_TO_NAME.update({f"F{i}": f"f{i}" for i in range(1, 25)})

_MODIFIER_KEYSYMS = {k: v for k, v in KEYSYM_TO_NAME.items() if v in MODIFIERS}

_ALIASES = {
    "control": "ctrl", "escape": "esc", "return": "enter", "win": "cmd",
    "windows": "cmd", "del": "delete", "ins": "insert", "pgup": "page_up",
    "pgdn": "page_down", "plus": "=", "comma": ",", "minus": "-",
}


def is_valid(name: str) -> bool:
    return name in _VALID


def is_modifier(name: str) -> bool:
    return name in MODIFIERS


def display_name(name: str) -> str:
    if name in _DISPLAY:
        return _DISPLAY[name]
    if len(name) == 1:
        return name.upper()
    if name.startswith("num") and name[3:].isdigit():
        return f"Num {name[3:]}"
    return name.replace("_", " ").title()


def format_chord(keys: list[str]) -> str:
    return "+".join(display_name(k) for k in keys) if keys else "-"


def search(query: str, group: str | None = None) -> list[str]:
    """Keys whose name or display name contains the query; exact and prefix matches first."""
    pool = KEY_GROUPS.get(group, ALL_KEYS) if group else ALL_KEYS
    needle = " ".join(query.lower().split())
    if not needle:
        return list(pool)
    ranked = []
    for index, name in enumerate(pool):
        texts = (name, display_name(name).lower())
        if any(needle in text for text in texts):
            exact = needle in texts
            prefix = any(text.startswith(needle) for text in texts)
            ranked.append((not exact, not prefix, index, name))
    return [name for *_rank, name in sorted(ranked)]


def parse_chord(text: str) -> list[str]:
    """Parse "ctrl+shift+s" into ["ctrl", "shift", "s"]; raises ValueError."""
    keys: list[str] = []
    for raw in text.replace(" ", "").split("+"):
        if not raw:
            continue
        token = raw.lower()
        token = _ALIASES.get(token, token)
        if not is_valid(token):
            raise ValueError(f"Unknown key: {raw}")
        if token not in keys:
            keys.append(token)
    if not keys:
        raise ValueError("Enter a key, e.g. w, space or ctrl+c")
    if len(keys) > 4:
        raise ValueError("Use at most 4 keys in one chord")
    return keys


def name_from_tk(keysym: str, keycode: int, windows: bool) -> str | None:
    """Translate a Tk key event into a profile key name (None if unsupported)."""
    if keysym in _MODIFIER_KEYSYMS:  # keysym keeps left/right sides apart
        return _MODIFIER_KEYSYMS[keysym]
    if windows and keycode in VK_TO_NAME:  # Tk reports the Windows VK code
        return VK_TO_NAME[keycode]
    if keysym in KEYSYM_TO_NAME:
        return KEYSYM_TO_NAME[keysym]
    if len(keysym) == 1 and keysym.lower() in _VALID:
        return keysym.lower()
    return None
