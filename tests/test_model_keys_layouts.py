import json

import pytest

from app import defaults, keys, layouts, model


def test_parse_chord_and_aliases():
    assert keys.parse_chord("Ctrl+Shift+S") == ["ctrl", "shift", "s"]
    assert keys.parse_chord("control + escape") == ["ctrl", "esc"]
    assert keys.format_chord(["ctrl", "page_up"]) == "Ctrl+Page Up"


@pytest.mark.parametrize("text", ["", "ctrl+foo", "a+b+c+d+e"])
def test_parse_chord_rejects_bad_input(text):
    with pytest.raises(ValueError):
        keys.parse_chord(text)


def test_tk_key_translation():
    assert keys.name_from_tk("Shift_R", 16, True) == "shift_r"
    assert keys.name_from_tk("a", 0x41, True) == "a"
    assert keys.name_from_tk("Return", 13, True) == "enter"
    assert keys.name_from_tk("F5", 0x74, False) == "f5"
    assert keys.name_from_tk("dead_acute", 0, False) is None


@pytest.mark.parametrize("name", defaults.TEMPLATE_NAMES)
def test_templates_round_trip_through_normalize(name):
    profile = defaults.template(name)
    assert model.normalize_profile(json.loads(json.dumps(profile))) == profile


def test_default_profile_files_match_templates(tmp_path):
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    for name in defaults.TEMPLATE_NAMES:
        text = (repo / "profiles" / defaults.TEMPLATE_FILES[name]).read_text(encoding="utf-8")
        assert text == json.dumps(defaults.template(name), indent=2, ensure_ascii=False) + "\n"


def test_normalize_repairs_hostile_profiles():
    profile = model.normalize_profile({
        "name": "  x\n y ",
        "anti_drift": {"threshold": "nan", "delay_ms": 10**9},
        "buttons": {"a": {"press": {"type": "key", "keys": ["nope", "w", "w"], "mode": "x"},
                          "hold_ms": -5},
                    "b": "garbage"},
        "sticks": {"left": {"deadzone": 5, "outer": 0.0, "zone_count": 3, "mode": "?"}},
        "triggers": {"lt": {"activation": 0.9, "full": 0.1}},
        "calibration": {"guid": {"axes": {"0": 9, "x": 1}}},
    })
    assert profile["name"] == "x y"
    assert profile["anti_drift"]["threshold"] == model.DEFAULT_ANTI_DRIFT
    assert profile["anti_drift"]["delay_ms"] == 2000
    assert profile["buttons"]["a"]["press"] == model.key_action("w", mode="hold")
    assert profile["buttons"]["a"]["hold_ms"] == 0
    assert profile["buttons"]["b"] == model.make_slot()
    left = profile["sticks"]["left"]
    assert left["deadzone"] == 0.9 and left["outer"] > left["deadzone"]
    assert left["zone_count"] == 8 and left["mode"] == "zones"
    lt = profile["triggers"]["lt"]
    assert lt["full"] > lt["activation"]
    assert profile["calibration"]["guid"]["axes"] == {"0": 1.0}
    with pytest.raises(ValueError):
        model.normalize_profile([])


def test_slot_addressing_covers_every_control():
    profile = model.new_profile("t")
    ids = model.all_slot_ids()
    assert len(ids) == len(set(ids)) == 11 + 8 + 2 * 9 + 2 * 2
    for slot_id in ids:
        assert model.get_slot(profile, slot_id) == model.make_slot()
        assert model.slot_title(slot_id)


def test_layout_presets_and_overrides():
    xinput = layouts.resolve("g", 6, 11, 1, {})
    assert xinput["base"] == "xinput" and xinput["bindings"]["rt"]["index"] == 5
    sdl = layouts.resolve("g", 6, 16, 0, {})
    assert sdl["base"] == "sdl" and sdl["bindings"]["dpad_up"]["kind"] == "button"
    custom = layouts.resolve("g", 6, 11, 1, {"g": {"preset": "xinput", "bindings": {
        "a": {"kind": "button", "index": 3}, "b": None, "x": {"kind": "bogus"}}}})
    assert custom["bindings"]["a"]["index"] == 3
    assert custom["bindings"]["b"] is None and custom["bindings"]["x"] is None


def test_read_helpers():
    axes, buttons, hats = (0.0, 0.0, -1.0, 0.0, 0.0, 1.0), (1, 0), ((1, -1),)
    assert layouts.read_digital({"kind": "button", "index": 0}, axes, buttons, hats)
    assert layouts.read_digital({"kind": "hat", "index": 0, "dir": "right"}, axes, buttons, hats)
    assert layouts.read_digital({"kind": "hat", "index": 0, "dir": "down"}, axes, buttons, hats)
    assert not layouts.read_digital({"kind": "hat", "index": 0, "dir": "up"}, axes, buttons, hats)
    assert layouts.read_digital(None, axes, buttons, hats) is False
    assert layouts.read_trigger({"kind": "axis", "index": 5, "rest": -1.0}, axes, buttons, hats, {}) == (1.0, -1.0)
    assert layouts.read_axis({"kind": "axis", "index": 5, "invert": True}, axes) == -1.0


def test_detect_binding():
    base = {"axes": [0.0, 0.0, -1.0], "buttons": [0, 0], "hats": [(0, 0)]}
    pressed = {**base, "buttons": [0, 1]}
    assert layouts.detect_binding("a", base, pressed) == {"kind": "button", "index": 1}
    hat = {**base, "hats": [(-1, 0)]}
    assert layouts.detect_binding("dpad_left", base, hat) == {"kind": "hat", "index": 0, "dir": "left"}
    pulled = {**base, "axes": [0.0, 0.0, 1.0]}
    assert layouts.detect_binding("lt", base, pulled) == {"kind": "axis", "index": 2, "rest": -1.0}
    pushed = {**base, "axes": [-1.0, 0.0, -1.0]}
    assert layouts.detect_binding("left_x", base, pushed) == {"kind": "axis", "index": 0, "invert": True}
    assert layouts.detect_binding("a", base, base) is None
