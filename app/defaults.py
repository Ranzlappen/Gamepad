"""The three built-in profile templates."""

from __future__ import annotations

from app.model import (
    DEFAULT_ANTI_DRIFT,
    DEFAULT_DEADZONE,
    key_action,
    make_slot,
    mouse_button_action,
    new_profile,
)

DESKTOP = "Desktop / Mouse"
FPS = "FPS Standard"
EMPTY = "Empty"
TEMPLATE_NAMES = (DESKTOP, FPS, EMPTY)
TEMPLATE_FILES = {DESKTOP: "desktop-mouse.json", FPS: "fps-standard.json", EMPTY: "empty.json"}


def _key(*names: str, mode: str = "hold") -> dict:
    return make_slot(key_action(*names, mode=mode))


def _wasd(profile: dict) -> None:
    left = profile["sticks"]["left"]
    left["diagonal_mode"] = "cardinals"  # up-right presses W and D together
    for zone, key in (("n", "w"), ("w", "a"), ("s", "s"), ("e", "d")):
        left["zones"][zone] = _key(key)


def _mouse_look(profile: dict, speed: float, curve: float, accel: float) -> None:
    right = profile["sticks"]["right"]
    right["mode"] = "mouse"
    right["mouse"] = {"speed": speed, "curve": curve, "accel": accel}


def _desktop() -> dict:
    p = new_profile(DESKTOP)
    p["description"] = "Left stick WASD, right stick mouse, triggers click, face buttons shortcuts."
    _wasd(p)
    _mouse_look(p, speed=1200.0, curve=1.6, accel=0.0)
    p["triggers"]["rt"]["zones"]["soft"] = make_slot(mouse_button_action("left"))
    p["triggers"]["lt"]["zones"]["soft"] = make_slot(mouse_button_action("right"))
    b = p["buttons"]
    b["a"] = _key("enter")
    b["b"] = _key("esc")
    b["x"] = _key("ctrl", "c", mode="tap")
    b["y"] = _key("ctrl", "v", mode="tap")
    b["lb"] = _key("ctrl", "shift", "tab", mode="tap")
    b["rb"] = _key("ctrl", "tab", mode="tap")
    b["back"] = _key("alt", "tab", mode="tap")
    b["start"] = _key("cmd", mode="tap")
    b["rs"] = make_slot(mouse_button_action("middle"))
    dpad = p["dpad"]
    dpad["diagonal_mode"] = "cardinals"
    for zone, key in (("n", "up"), ("s", "down"), ("w", "left"), ("e", "right")):
        dpad["zones"][zone] = _key(key)
    return p


def _fps() -> dict:
    p = new_profile(FPS)
    p["description"] = "WASD movement, mouse look, fire/aim on triggers, lean/grenade on bumpers."
    _wasd(p)
    p["sticks"]["left"]["zones"]["outer"] = _key("shift")  # full deflection sprints
    _mouse_look(p, speed=1400.0, curve=1.8, accel=0.5)
    p["triggers"]["rt"]["zones"]["soft"] = make_slot(mouse_button_action("left"))
    p["triggers"]["lt"]["zones"]["soft"] = make_slot(mouse_button_action("right"))
    b = p["buttons"]
    b["a"] = _key("space")
    b["b"] = _key("ctrl")
    b["x"] = _key("r")
    b["y"] = _key("e")
    b["lb"] = _key("q")
    b["rb"] = _key("g")
    b["ls"] = _key("shift")
    b["rs"] = _key("v")
    b["back"] = _key("tab")
    b["start"] = _key("esc", mode="tap")
    for zone, key in (("n", "1"), ("e", "2"), ("s", "3"), ("w", "4")):
        p["dpad"]["zones"][zone] = _key(key, mode="tap")
    return p


def template(name: str, deadzone: float = DEFAULT_DEADZONE,
             anti_drift: float = DEFAULT_ANTI_DRIFT) -> dict:
    """Return a fresh copy of a template; Empty uses the given default thresholds."""
    if name == DESKTOP:
        return _desktop()
    if name == FPS:
        return _fps()
    return new_profile(EMPTY, deadzone=deadzone, anti_drift=anti_drift)
