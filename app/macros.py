"""Macros: validated step lists, summaries, and conversion of recorded input.

A macro is a list of steps that the engine runs in order, one tick at a time:

    {"op": "key_down", "key": "ctrl"}        {"op": "key_up", "key": "ctrl"}
    {"op": "button_down", "button": "left"}  {"op": "button_up", "button": "left"}
    {"op": "wait", "ms": 120}

Keys and mouse buttons use the same names as key and mouse-button actions, so a
macro can only express what a normal mapping can. Anything a macro leaves held
is released by the engine when the macro ends.
"""

from __future__ import annotations

import math
from typing import Any

from app import keys

OPS = ("key_down", "key_up", "button_down", "button_up", "wait")
MAX_STEPS = 500
MAX_WAIT_MS = 10000
DEFAULT_GAP_MS = 30  # key-down time of added taps, and the delay when recording without timing

_ARROWS = {"key_down": "↓", "key_up": "↑", "button_down": "↓", "button_up": "↑"}
_BUTTON_NAMES = {"left": "Left click", "right": "Right click", "middle": "Middle click",
                 "x1": "Back (X1)", "x2": "Forward (X2)"}
_BUTTON_SHORT = {"left": "LMB", "right": "RMB", "middle": "MMB", "x1": "X1", "x2": "X2"}


def key_step(op: str, key: str) -> dict:
    return {"op": op, "key": key}


def button_step(op: str, button: str) -> dict:
    return {"op": op, "button": button}


def wait_step(ms: float) -> dict:
    return {"op": "wait", "ms": int(round(min(max(ms, 0), MAX_WAIT_MS)))}


def normalize_step(data: Any) -> dict | None:
    """One validated step, or None for anything unknown or invalid."""
    if not isinstance(data, dict):
        return None
    op = data.get("op")
    if op in ("key_down", "key_up"):
        key = data.get("key")
        return key_step(op, key) if isinstance(key, str) and keys.is_valid(key) else None
    if op in ("button_down", "button_up"):
        button = data.get("button")
        return button_step(op, button) if button in keys.MOUSE_BUTTONS else None
    if op == "wait":
        try:
            ms = float(data.get("ms"))
        except (TypeError, ValueError):
            return None
        return wait_step(ms) if math.isfinite(ms) else None
    return None


def normalize_steps(data: Any) -> list[dict]:
    if not isinstance(data, list):
        return []
    steps = []
    for item in data:
        step = normalize_step(item)
        if step is not None:
            steps.append(step)
            if len(steps) >= MAX_STEPS:
                break
    return steps


def tap_steps(names: list[str], gap_ms: int = DEFAULT_GAP_MS) -> list[dict]:
    """Press a key or chord, hold it briefly, release it in reverse order."""
    return ([key_step("key_down", n) for n in names] + [wait_step(gap_ms)]
            + [key_step("key_up", n) for n in reversed(names)])


def click_steps(button: str, gap_ms: int = DEFAULT_GAP_MS) -> list[dict]:
    return [button_step("button_down", button), wait_step(gap_ms), button_step("button_up", button)]


def set_all_delays(steps: list[dict], ms: int) -> list[dict]:
    """Every wait set to ms; 0 removes the waits (keys and buttons stay in order)."""
    if ms <= 0:
        return [s for s in steps if s["op"] != "wait"]
    return [wait_step(ms) if s["op"] == "wait" else s for s in steps]


def steps_from_events(events: list[tuple[int, str, str]], *, record_delays: bool = True,
                      gap_ms: int = DEFAULT_GAP_MS) -> list[dict]:
    """Recorded (time_ms, op, name) events, in order, as steps with waits between them."""
    steps: list[dict] = []
    last: int | None = None
    for time_ms, op, name in events:
        if last is not None:
            ms = time_ms - last if record_delays else gap_ms
            if ms > 0:  # event clocks can wrap around; never record a negative wait
                steps.append(wait_step(ms))
        last = time_ms
        steps.append(key_step(op, name) if op.startswith("key") else button_step(op, name))
    return steps[:MAX_STEPS]


def duration_ms(steps: list[dict]) -> int:
    return sum(s["ms"] for s in steps if s["op"] == "wait")


def describe_step(step: dict) -> str:
    op = step["op"]
    if op == "wait":
        return f"Wait {step['ms']} ms"
    verb = "Press" if op.endswith("down") else "Release"
    if op.startswith("key"):
        return f"{verb} {keys.display_name(step['key'])}"
    return f"{verb} mouse {_BUTTON_NAMES[step['button']].lower()}"


def short_step(step: dict) -> str:
    op = step["op"]
    if op == "wait":
        return f"{step['ms']}ms"
    name = keys.display_name(step["key"]) if op.startswith("key") else _BUTTON_SHORT[step["button"]]
    return f"{name}{_ARROWS[op]}"


def summary(steps: list[dict]) -> str:
    if not steps:
        return "empty"
    count = len(steps)
    return f"{count} step{'s' if count != 1 else ''}, {duration_ms(steps) / 1000:.2f} s"


def preview(steps: list[dict], limit: int = 12) -> str:
    text = " ".join(short_step(s) for s in steps[:limit])
    return text + (" ..." if len(steps) > limit else "")
