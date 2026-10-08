"""Profile schema: logical controls, slots, actions, defaults and normalization.

A profile maps every logical control of a generic controller to one or more
*slots*. A slot holds up to three actions:

* ``press``   - starts when the control activates (held until it deactivates
  for "hold" keys/buttons and mouse movement, or tapped once for "tap").
* ``tap``     - fires on release when the control was held shorter than
  ``hold_ms``; ``press`` then only starts once the hold time is reached.
* ``release`` - fires (as a tap) when the control deactivates.
"""

from __future__ import annotations

import math
from typing import Any

from app import keys

SCHEMA_VERSION = 1

BUTTONS = ("a", "b", "x", "y", "lb", "rb", "back", "start", "guide", "ls", "rs")
BUTTON_LABELS = {
    "a": "A", "b": "B", "x": "X", "y": "Y", "lb": "Left bumper", "rb": "Right bumper",
    "back": "Back / View", "start": "Start / Menu", "guide": "Guide",
    "ls": "Left stick click", "rs": "Right stick click",
}

DIRECTIONS = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
DIRECTION_LABELS = {
    "n": "Up", "ne": "Up-right", "e": "Right", "se": "Down-right",
    "s": "Down", "sw": "Down-left", "w": "Left", "nw": "Up-left",
}
DIRECTION_ARROWS = {
    "n": "↑", "ne": "↗", "e": "→", "se": "↘",
    "s": "↓", "sw": "↙", "w": "←", "nw": "↖",
}
DIAGONALS = {"ne": ("n", "e"), "se": ("s", "e"), "sw": ("s", "w"), "nw": ("n", "w")}
_INV_SQRT2 = 1 / math.sqrt(2)
# Unit vectors in screen space (x right, y down).
DIRECTION_VECTORS = {
    "n": (0.0, -1.0), "ne": (_INV_SQRT2, -_INV_SQRT2), "e": (1.0, 0.0),
    "se": (_INV_SQRT2, _INV_SQRT2), "s": (0.0, 1.0), "sw": (-_INV_SQRT2, _INV_SQRT2),
    "w": (-1.0, 0.0), "nw": (-_INV_SQRT2, -_INV_SQRT2),
}

STICKS = ("left", "right")
STICK_LABELS = {"left": "Left stick", "right": "Right stick"}
STICK_ZONES = DIRECTIONS + ("outer",)
TRIGGERS = ("lt", "rt")
TRIGGER_LABELS = {"lt": "Left trigger", "rt": "Right trigger"}
TRIGGER_ZONES = ("soft", "full")
TRIGGER_ZONE_LABELS = {"soft": "Activation", "full": "Full press"}

ACTION_TYPES = ("none", "key", "mouse_button", "mouse_move")
TAP_ACTION_TYPES = ("none", "key", "mouse_button")
ACTION_MODES = ("hold", "tap")
MOUSE_BUTTONS = ("left", "right", "middle", "x1", "x2")
DIAGONAL_MODES = ("combined", "cardinals")
STICK_MODES = ("zones", "mouse")
RESPONSES = ("linear", "curved")

DEFAULT_DEADZONE = 0.15
DEFAULT_OUTER = 0.90
DEFAULT_ANTI_DRIFT = 0.08
DEFAULT_DRIFT_DELAY_MS = 300
DEFAULT_TRIGGER_ACTIVATION = 0.15
DEFAULT_TRIGGER_FULL = 0.90
DEFAULT_MOUSE_SPEED = 1200.0
MAX_NAME_LENGTH = 60


# --- small numeric helpers -------------------------------------------------

def clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def as_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def pick(value: Any, allowed: tuple, default: Any) -> Any:
    return value if value in allowed else default


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def clean_name(value: Any) -> str:
    """Collapse whitespace and cap the length of a profile name ('' if unusable)."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:MAX_NAME_LENGTH]


# --- actions and slots -----------------------------------------------------

def no_action() -> dict:
    return {"type": "none"}


def key_action(*names: str, mode: str = "hold") -> dict:
    return {"type": "key", "keys": list(names), "mode": mode}


def mouse_button_action(button: str, mode: str = "hold") -> dict:
    return {"type": "mouse_button", "button": button, "mode": mode}


def mouse_move_action(direction: str, speed: float = 600.0, accel: float = 0.0) -> dict:
    return {"type": "mouse_move", "direction": direction, "speed": speed, "accel": accel}


def make_slot(press: dict | None = None, *, hold_ms: int = 0,
              tap: dict | None = None, release: dict | None = None) -> dict:
    return {
        "press": press or no_action(),
        "hold_ms": hold_ms,
        "tap": tap or no_action(),
        "release": release or no_action(),
    }


def default_action(action_type: str, *, tap_only: bool = False) -> dict:
    mode = "tap" if tap_only else "hold"
    if action_type == "key":
        return key_action("space", mode=mode)
    if action_type == "mouse_button":
        return mouse_button_action("left", mode=mode)
    if action_type == "mouse_move" and not tap_only:
        return mouse_move_action("e")
    return no_action()


def normalize_action(data: Any, *, tap_only: bool = False) -> dict:
    a = _dict(data)
    kind = a.get("type")
    allowed = TAP_ACTION_TYPES if tap_only else ACTION_TYPES
    if kind not in allowed or kind == "none":
        return no_action()
    mode = "tap" if tap_only else pick(a.get("mode"), ACTION_MODES, "hold")
    if kind == "key":
        names = a.get("keys")
        names = [n for n in names if isinstance(n, str) and keys.is_valid(n)] if isinstance(names, list) else []
        names = list(dict.fromkeys(names))[:4]
        return key_action(*names, mode=mode) if names else no_action()
    if kind == "mouse_button":
        return mouse_button_action(pick(a.get("button"), MOUSE_BUTTONS, "left"), mode)
    return mouse_move_action(
        pick(a.get("direction"), DIRECTIONS, "e"),
        clamp(as_float(a.get("speed"), 600.0), 10.0, 5000.0),
        clamp(as_float(a.get("accel"), 0.0), 0.0, 5.0),
    )


def normalize_slot(data: Any) -> dict:
    s = _dict(data)
    return make_slot(
        normalize_action(s.get("press")),
        hold_ms=int(clamp(as_float(s.get("hold_ms"), 0), 0, 5000)),
        tap=normalize_action(s.get("tap"), tap_only=True),
        release=normalize_action(s.get("release"), tap_only=True),
    )


def slot_is_mapped(slot: dict) -> bool:
    return any(slot[k]["type"] != "none" for k in ("press", "tap", "release"))


# --- profiles --------------------------------------------------------------

def _stick(deadzone: float) -> dict:
    return {
        "mode": "zones",
        "deadzone": deadzone,
        "outer": max(DEFAULT_OUTER, deadzone + 0.05),
        "zone_count": 8,
        "diagonal_mode": "combined",
        "mouse": {"speed": DEFAULT_MOUSE_SPEED, "curve": 1.5, "accel": 0.0},
        "zones": {z: make_slot() for z in STICK_ZONES},
    }


def _trigger() -> dict:
    return {
        "activation": DEFAULT_TRIGGER_ACTIVATION,
        "full": DEFAULT_TRIGGER_FULL,
        "response": "linear",
        "curve_exponent": 2.0,
        "zones": {z: make_slot() for z in TRIGGER_ZONES},
    }


def new_profile(name: str, deadzone: float = DEFAULT_DEADZONE,
                anti_drift: float = DEFAULT_ANTI_DRIFT) -> dict:
    """An empty profile: every slot exists and is unmapped."""
    return {
        "schema": SCHEMA_VERSION,
        "name": name,
        "description": "",
        "anti_drift": {"threshold": anti_drift, "delay_ms": DEFAULT_DRIFT_DELAY_MS},
        "calibration": {},
        "buttons": {b: make_slot() for b in BUTTONS},
        "dpad": {"diagonal_mode": "combined", "zones": {d: make_slot() for d in DIRECTIONS}},
        "sticks": {s: _stick(deadzone) for s in STICKS},
        "triggers": {t: _trigger() for t in TRIGGERS},
    }


def _normalize_calibration(data: Any) -> dict:
    result = {}
    for guid, entry in _dict(data).items():
        entry = _dict(entry)
        axes = {}
        for index, value in _dict(entry.get("axes")).items():
            if str(index).isdigit():
                axes[str(int(index))] = round(clamp(as_float(value, 0.0), -1.0, 1.0), 4)
        if isinstance(guid, str) and axes:
            result[guid] = {
                "device": str(entry.get("device", ""))[:80],
                "updated": str(entry.get("updated", ""))[:40],
                "axes": axes,
            }
    return result


def normalize_profile(data: Any, fallback_name: str = "Imported profile") -> dict:
    """Return a complete, valid profile built from untrusted JSON data."""
    if not isinstance(data, dict):
        raise ValueError("A profile must be a JSON object")
    profile = new_profile(clean_name(data.get("name")) or fallback_name)
    profile["description"] = str(data.get("description", ""))[:200]

    drift = _dict(data.get("anti_drift"))
    profile["anti_drift"] = {
        "threshold": clamp(as_float(drift.get("threshold"), DEFAULT_ANTI_DRIFT), 0.0, 0.5),
        "delay_ms": int(clamp(as_float(drift.get("delay_ms"), DEFAULT_DRIFT_DELAY_MS), 0, 2000)),
    }
    profile["calibration"] = _normalize_calibration(data.get("calibration"))

    buttons = _dict(data.get("buttons"))
    for b in BUTTONS:
        profile["buttons"][b] = normalize_slot(buttons.get(b))

    dpad = _dict(data.get("dpad"))
    profile["dpad"]["diagonal_mode"] = pick(dpad.get("diagonal_mode"), DIAGONAL_MODES, "combined")
    for d in DIRECTIONS:
        profile["dpad"]["zones"][d] = normalize_slot(_dict(dpad.get("zones")).get(d))

    for s in STICKS:
        src, dst = _dict(_dict(data.get("sticks")).get(s)), profile["sticks"][s]
        dst["mode"] = pick(src.get("mode"), STICK_MODES, "zones")
        dst["deadzone"] = clamp(as_float(src.get("deadzone"), dst["deadzone"]), 0.0, 0.9)
        dst["outer"] = clamp(as_float(src.get("outer"), dst["outer"]), dst["deadzone"] + 0.05, 1.0)
        dst["zone_count"] = 4 if src.get("zone_count") == 4 else 8
        dst["diagonal_mode"] = pick(src.get("diagonal_mode"), DIAGONAL_MODES, "combined")
        mouse = _dict(src.get("mouse"))
        dst["mouse"] = {
            "speed": clamp(as_float(mouse.get("speed"), DEFAULT_MOUSE_SPEED), 50.0, 5000.0),
            "curve": clamp(as_float(mouse.get("curve"), 1.5), 1.0, 3.0),
            "accel": clamp(as_float(mouse.get("accel"), 0.0), 0.0, 5.0),
        }
        for z in STICK_ZONES:
            dst["zones"][z] = normalize_slot(_dict(src.get("zones")).get(z))

    for t in TRIGGERS:
        src, dst = _dict(_dict(data.get("triggers")).get(t)), profile["triggers"][t]
        dst["activation"] = clamp(as_float(src.get("activation"), dst["activation"]), 0.02, 0.95)
        dst["full"] = clamp(as_float(src.get("full"), dst["full"]), dst["activation"] + 0.02, 1.0)
        dst["response"] = pick(src.get("response"), RESPONSES, "linear")
        dst["curve_exponent"] = clamp(as_float(src.get("curve_exponent"), 2.0), 0.3, 4.0)
        for z in TRIGGER_ZONES:
            dst["zones"][z] = normalize_slot(_dict(src.get("zones")).get(z))
    return profile


# --- slot addressing -------------------------------------------------------

def all_slot_ids() -> list[str]:
    ids = [f"button:{b}" for b in BUTTONS] + [f"dpad:{d}" for d in DIRECTIONS]
    for s in STICKS:
        ids += [f"stick:{s}:{z}" for z in STICK_ZONES]
    for t in TRIGGERS:
        ids += [f"trigger:{t}:{z}" for z in TRIGGER_ZONES]
    return ids


def get_slot(profile: dict, slot_id: str) -> dict:
    parts = slot_id.split(":")
    if parts[0] == "button":
        return profile["buttons"][parts[1]]
    if parts[0] == "dpad":
        return profile["dpad"]["zones"][parts[1]]
    if parts[0] == "stick":
        return profile["sticks"][parts[1]]["zones"][parts[2]]
    if parts[0] == "trigger":
        return profile["triggers"][parts[1]]["zones"][parts[2]]
    raise KeyError(slot_id)


def slot_title(slot_id: str) -> str:
    parts = slot_id.split(":")
    if parts[0] == "button":
        return BUTTON_LABELS[parts[1]]
    if parts[0] == "dpad":
        return f"D-pad {DIRECTION_LABELS[parts[1]].lower()}"
    if parts[0] == "stick":
        zone = "outer ring" if parts[2] == "outer" else DIRECTION_LABELS[parts[2]].lower()
        return f"{STICK_LABELS[parts[1]]} {zone}"
    return f"{TRIGGER_LABELS[parts[1]]} {TRIGGER_ZONE_LABELS[parts[2]].lower()}"


# --- human-readable summaries ----------------------------------------------

def describe_action(action: dict, show_mode: bool = True) -> str:
    kind = action["type"]
    if kind in ("key", "mouse_button"):
        if kind == "key":
            text = keys.format_chord(action["keys"])
        else:
            text = f"{action['button'].title()} click"
        return f"tap {text}" if show_mode and action.get("mode") == "tap" else text
    if kind == "mouse_move":
        return f"Mouse {DIRECTION_ARROWS[action['direction']]} {action['speed']:.0f}px/s"
    return "-"


def describe_slot(slot: dict) -> str:
    parts = []
    if slot["press"]["type"] != "none":
        parts.append(describe_action(slot["press"]))
    if slot["hold_ms"] > 0 and slot["tap"]["type"] != "none":
        parts.append(f"tap: {describe_action(slot['tap'], False)}")
    if slot["release"]["type"] != "none":
        parts.append(f"release: {describe_action(slot['release'], False)}")
    return ", ".join(parts) if parts else "not mapped"
