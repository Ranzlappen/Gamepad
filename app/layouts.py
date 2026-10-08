"""Raw-input layouts: which SDL button, axis or hat drives each logical control.

pygame exposes controllers through SDL's raw joystick API, whose index order
depends on the driver (XInput, Windows.Gaming.Input, RawInput, HIDAPI, ...).
"Auto-detect" therefore asks SDL for its own game-controller mapping of the
device and only falls back to a preset when SDL does not know the controller.
Any control can still be re-bound per controller (keyed by GUID) with "Detect".
Bindings are plain dicts so they serialise straight into settings.json:

    {"kind": "button", "index": 0}
    {"kind": "hat", "index": 0, "dir": "up"}
    {"kind": "axis", "index": 2, "invert": false}        stick axis
    {"kind": "axis", "index": 2, "rest": -1.0}           analog trigger
    {"kind": "axis", "index": 2, "rest": 0.0, "invert": true}   trigger on an axis half
    {"kind": "axis", "index": 2, "sign": 1}              axis used as a button
"""

from __future__ import annotations

import copy
from typing import Any

from app.model import BUTTON_LABELS, BUTTONS, as_float

DPAD_CONTROLS = ("dpad_up", "dpad_down", "dpad_left", "dpad_right")
STICK_AXES = ("left_x", "left_y", "right_x", "right_y")
TRIGGER_CONTROLS = ("lt", "rt")
LAYOUT_CONTROLS = BUTTONS + DPAD_CONTROLS + STICK_AXES + TRIGGER_CONTROLS

CONTROL_LABELS = {
    **BUTTON_LABELS,
    "dpad_up": "D-pad up", "dpad_down": "D-pad down", "dpad_left": "D-pad left",
    "dpad_right": "D-pad right", "left_x": "Left stick X", "left_y": "Left stick Y",
    "right_x": "Right stick X", "right_y": "Right stick Y",
    "lt": "Left trigger", "rt": "Right trigger",
}

DETECT_PROMPTS = {
    "left_x": "Push the LEFT stick fully to the RIGHT",
    "left_y": "Push the LEFT stick fully DOWN",
    "right_x": "Push the RIGHT stick fully to the RIGHT",
    "right_y": "Push the RIGHT stick fully DOWN",
    "lt": "Pull the LEFT trigger all the way",
    "rt": "Pull the RIGHT trigger all the way",
}

HAT_DIRECTIONS = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}


def _b(index: int) -> dict:
    return {"kind": "button", "index": index}


def _hat(direction: str) -> dict:
    return {"kind": "hat", "index": 0, "dir": direction}


def _axis(index: int) -> dict:
    return {"kind": "axis", "index": index, "invert": False}


def _trigger(index: int) -> dict:
    return {"kind": "axis", "index": index, "rest": -1.0}


PRESETS: dict[str, dict[str, Any]] = {
    # SDL's XInput driver (Xbox and most PC pads); D-pad on hat 0.
    "xinput": {
        "label": "XInput (Xbox and most PC pads)",
        "bindings": {
            "a": _b(0), "b": _b(1), "x": _b(2), "y": _b(3), "lb": _b(4), "rb": _b(5),
            "back": _b(6), "start": _b(7), "ls": _b(8), "rs": _b(9), "guide": _b(10),
            "dpad_up": _hat("up"), "dpad_down": _hat("down"),
            "dpad_left": _hat("left"), "dpad_right": _hat("right"),
            "left_x": _axis(0), "left_y": _axis(1), "right_x": _axis(3), "right_y": _axis(4),
            "lt": _trigger(2), "rt": _trigger(5),
        },
    },
    # Xbox pads through SDL's Windows.Gaming.Input / RawInput drivers: XInput button order,
    # D-pad on hat 0, but the axes in game-controller order (both sticks, then both triggers).
    "xbox_modern": {
        "label": "Xbox (Windows.Gaming.Input / RawInput)",
        "bindings": {
            "a": _b(0), "b": _b(1), "x": _b(2), "y": _b(3), "lb": _b(4), "rb": _b(5),
            "back": _b(6), "start": _b(7), "ls": _b(8), "rs": _b(9), "guide": _b(10),
            "dpad_up": _hat("up"), "dpad_down": _hat("down"),
            "dpad_left": _hat("left"), "dpad_right": _hat("right"),
            "left_x": _axis(0), "left_y": _axis(1), "right_x": _axis(2), "right_y": _axis(3),
            "lt": _trigger(4), "rt": _trigger(5),
        },
    },
    # SDL's HIDAPI drivers (PlayStation, Switch Pro, ...): game-controller order, D-pad as buttons.
    "sdl": {
        "label": "SDL standard (PlayStation, Switch Pro)",
        "bindings": {
            "a": _b(0), "b": _b(1), "x": _b(2), "y": _b(3), "back": _b(4), "guide": _b(5),
            "start": _b(6), "ls": _b(7), "rs": _b(8), "lb": _b(9), "rb": _b(10),
            "dpad_up": _b(11), "dpad_down": _b(12), "dpad_left": _b(13), "dpad_right": _b(14),
            "left_x": _axis(0), "left_y": _axis(1), "right_x": _axis(2), "right_y": _axis(3),
            "lt": _trigger(4), "rt": _trigger(5),
        },
    },
}
PRESET_CHOICES = ("auto",) + tuple(PRESETS)
PRESET_LABELS = {"auto": "Auto-detect", **{k: v["label"] for k, v in PRESETS.items()}}
SDL_MAPPING = "sdl_mapping"  # resolved base when SDL's own mapping is used
BASE_LABELS = {**PRESET_LABELS, SDL_MAPPING: "SDL's built-in mapping for this controller"}

# SDL game-controller mapping keys -> logical controls
# (https://wiki.libsdl.org/SDL2/SDL_GameControllerAddMapping).
_SDL_KEYS = {
    "a": "a", "b": "b", "x": "x", "y": "y", "back": "back", "guide": "guide", "start": "start",
    "leftstick": "ls", "rightstick": "rs", "leftshoulder": "lb", "rightshoulder": "rb",
    "dpup": "dpad_up", "dpdown": "dpad_down", "dpleft": "dpad_left", "dpright": "dpad_right",
    "leftx": "left_x", "lefty": "left_y", "rightx": "right_x", "righty": "right_y",
    "lefttrigger": "lt", "righttrigger": "rt",
}
_SDL_HAT_BITS = {1: "up", 2: "right", 4: "down", 8: "left"}


def auto_preset(num_axes: int, num_buttons: int, num_hats: int) -> str:
    if num_hats == 0 and num_buttons >= 15:
        return "sdl"
    return "xinput"


def _parse_sdl_value(control: str, value: str) -> dict | None:
    """One SDL mapping value ("b3", "a2", "a2~", "+a2", "-a2", "h0.4") as a binding."""
    try:
        if value.startswith("b"):
            return _b(int(value[1:]))
        if value.startswith("h"):
            hat, bit = value[1:].split(".")
            direction = _SDL_HAT_BITS.get(int(bit))
            return {"kind": "hat", "index": int(hat), "dir": direction} if direction else None
        half = value[0] if value[0] in "+-" else ""
        inverted = value.endswith("~")
        core = value[len(half):len(value) - int(inverted)]
        if not core.startswith("a"):
            return None
        index = int(core[1:])
    except (ValueError, IndexError):
        return None
    if control in STICK_AXES:
        return None if half else {"kind": "axis", "index": index, "invert": inverted}
    if control in TRIGGER_CONTROLS:
        if inverted:
            return None
        if half:  # trigger on one half of a shared axis (DirectInput-style Z axis)
            return {"kind": "axis", "index": index, "rest": 0.0, "invert": half == "-"}
        return {"kind": "axis", "index": index, "rest": -1.0}
    return {"kind": "axis", "index": index, "sign": -1 if half == "-" else 1}


def bindings_from_sdl_mapping(mapping: Any) -> dict[str, dict | None]:
    """Translate SDL's game-controller mapping (dict or key/value pairs) into bindings.

    Controls the mapping does not mention are left unbound rather than guessed.
    Returns {} when the mapping does not even cover the left stick.
    """
    pairs = mapping.items() if isinstance(mapping, dict) else mapping
    bindings: dict[str, dict | None] = dict.fromkeys(LAYOUT_CONTROLS)
    for key, value in pairs or ():
        control = _SDL_KEYS.get(str(key))
        if control and isinstance(value, str) and value:
            bindings[control] = _parse_sdl_value(control, value)
    if not (bindings["left_x"] and bindings["left_y"]):
        return {}
    return bindings


def normalize_binding(data: Any) -> dict | None:
    """Validate a binding from settings.json; None means "not bound"."""
    if not isinstance(data, dict) or not isinstance(data.get("index"), int):
        return None
    index = data["index"]
    if not 0 <= index < 256:
        return None
    kind = data.get("kind")
    if kind == "button":
        return _b(index)
    if kind == "hat" and data.get("dir") in HAT_DIRECTIONS:
        return {"kind": "hat", "index": index, "dir": data["dir"]}
    if kind == "axis":
        binding: dict[str, Any] = {"kind": "axis", "index": index}
        if "rest" in data:
            binding["rest"] = -1.0 if as_float(data.get("rest"), -1.0) < -0.5 else 0.0
            if data.get("invert"):
                binding["invert"] = True
        elif "sign" in data:
            binding["sign"] = -1 if data.get("sign") == -1 else 1
        else:
            binding["invert"] = bool(data.get("invert"))
        return binding
    return None


def _source(binding: dict) -> tuple:
    """The raw input a binding reads, for overlap checks."""
    if binding["kind"] == "hat":
        return ("hat", binding["index"], binding["dir"])
    return (binding["kind"], binding["index"])


def resolve(guid: str, num_axes: int, num_buttons: int, num_hats: int,
            overrides: dict, sdl_mapping: Any = ()) -> dict:
    """Effective layout for a controller: base bindings plus per-GUID overrides.

    The base is SDL's own mapping when "auto" and SDL knows the device, else a preset.
    """
    entry = overrides.get(guid) if isinstance(overrides.get(guid), dict) else {}
    preset = entry.get("preset", "auto")
    preset = preset if preset in PRESET_CHOICES else "auto"
    from_sdl = bindings_from_sdl_mapping(sdl_mapping) if preset == "auto" else {}
    if from_sdl:
        base, bindings = SDL_MAPPING, from_sdl
        # Fill controls SDL left out (e.g. a hat it does not map) from the preset guess,
        # but only with raw inputs the SDL mapping does not already use for something else.
        used = {_source(b) for b in bindings.values() if b}
        fallback = PRESETS[auto_preset(num_axes, num_buttons, num_hats)]["bindings"]
        for control, guess in fallback.items():
            if bindings[control] is None and _source(guess) not in used:
                bindings[control] = copy.deepcopy(guess)
                used.add(_source(guess))
    else:
        base = auto_preset(num_axes, num_buttons, num_hats) if preset == "auto" else preset
        bindings = copy.deepcopy(PRESETS[base]["bindings"])
    custom = entry.get("bindings") if isinstance(entry.get("bindings"), dict) else {}
    for control, value in custom.items():
        if control in LAYOUT_CONTROLS:
            bindings[control] = normalize_binding(value)
    return {"preset": preset, "base": base, "bindings": bindings, "custom": sorted(custom)}


def describe(binding: dict | None) -> str:
    if not binding:
        return "Not bound"
    kind, index = binding["kind"], binding["index"]
    if kind == "button":
        return f"Button {index}"
    if kind == "hat":
        return f"Hat {index} {binding['dir']}"
    if "rest" in binding:
        half = " inverted" if binding.get("invert") else ""
        return f"Axis {index}{half} (rest {binding['rest']:+.0f})"
    if "sign" in binding:
        return f"Axis {index} {'+' if binding['sign'] > 0 else '-'}"
    return f"Axis {index}{' inverted' if binding.get('invert') else ''}"


# --- reading raw state ---------------------------------------------------------

def _get(seq: tuple, index: int, default: Any) -> Any:
    return seq[index] if 0 <= index < len(seq) else default


def read_digital(binding: dict | None, axes: tuple, buttons: tuple, hats: tuple) -> bool:
    if not binding:
        return False
    kind, index = binding["kind"], binding["index"]
    if kind == "button":
        return bool(_get(buttons, index, 0))
    if kind == "hat":
        hx, hy = _get(hats, index, (0, 0))
        want_x, want_y = HAT_DIRECTIONS[binding["dir"]]
        return (want_x != 0 and hx == want_x) or (want_y != 0 and hy == want_y)
    value = _get(axes, index, 0.0)
    if "rest" in binding:
        return value - binding["rest"] > 0.5
    return value * binding.get("sign", 1) > 0.5


def read_axis(binding: dict | None, axes: tuple) -> float:
    if not binding or binding["kind"] != "axis":
        return 0.0
    value = _get(axes, binding["index"], 0.0)
    return -value if binding.get("invert") else value


def axis_rest(binding: dict | None, offsets: dict[int, float]) -> float:
    """Calibrated rest value of a stick axis in the same sign convention as read_axis."""
    if not binding or binding["kind"] != "axis":
        return 0.0
    rest = offsets.get(binding["index"], 0.0)
    return -rest if binding.get("invert") else rest


def read_trigger(binding: dict | None, axes: tuple, buttons: tuple, hats: tuple,
                 offsets: dict[int, float]) -> tuple[float, float]:
    """(value, rest) for a trigger; digital sources read as 0 or 1 with rest 0."""
    if not binding:
        return 0.0, 0.0
    if binding["kind"] == "axis":
        index = binding["index"]
        rest = offsets.get(index, binding.get("rest", -1.0))
        value = _get(axes, index, rest)
        if binding.get("invert"):  # trigger on the negative half of a shared axis
            return -value, -rest
        return value, rest
    return (1.0 if read_digital(binding, axes, buttons, hats) else 0.0), 0.0


def axis_roles(bindings: dict) -> dict[int, str]:
    """Which raw axes feed sticks and which feed triggers (used by calibration)."""
    roles: dict[int, str] = {}
    for control in STICK_AXES + TRIGGER_CONTROLS:
        b = bindings.get(control)
        if b and b["kind"] == "axis":
            roles[b["index"]] = "trigger" if control in TRIGGER_CONTROLS else "stick"
    return roles


def detect_binding(control: str, baseline: dict, current: dict) -> dict | None:
    """Find the raw input the user just actuated, relative to a resting baseline."""
    axes0, axes1 = baseline["axes"], current["axes"]
    deltas = [(abs(axes1[i] - axes0[i]), i) for i in range(min(len(axes0), len(axes1)))]
    moved = max(deltas, default=(0.0, -1))
    pressed = [i for i, (a, b) in enumerate(zip(baseline["buttons"], current["buttons"], strict=False))
               if b and not a]

    if control in STICK_AXES:
        if moved[0] < 0.5:
            return None
        i = moved[1]
        # The prompt asks for the positive SDL direction (right / down).
        return {"kind": "axis", "index": i, "invert": axes1[i] - axes0[i] < 0}
    if control in TRIGGER_CONTROLS:
        if moved[0] >= 0.5:
            i = moved[1]
            return {"kind": "axis", "index": i, "rest": -1.0 if axes0[i] < -0.5 else 0.0}
        return _b(pressed[0]) if pressed else None

    if pressed:
        return _b(pressed[0])
    for i, (h0, h1) in enumerate(zip(baseline["hats"], current["hats"], strict=False)):
        if tuple(h1) != tuple(h0) and tuple(h1) != (0, 0):
            for name, (dx, dy) in HAT_DIRECTIONS.items():
                if (dx and h1[0] == dx) or (dy and h1[1] == dy):
                    return {"kind": "hat", "index": i, "dir": name}
    if moved[0] >= 0.6:
        i = moved[1]
        return {"kind": "axis", "index": i, "sign": 1 if axes1[i] > axes0[i] else -1}
    return None
