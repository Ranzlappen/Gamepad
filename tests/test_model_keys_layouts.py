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


# --- SDL game-controller mappings ------------------------------------------------

XINPUT_MAPPING = (
    "a:b0,b:b1,back:b6,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,dpup:h0.1,guide:b10,"
    "leftshoulder:b4,leftstick:b8,lefttrigger:a2,leftx:a0,lefty:a1,rightshoulder:b5,"
    "rightstick:b9,righttrigger:a5,rightx:a3,righty:a4,start:b7,x:b2,y:b3")
# Xbox pad through Windows.Gaming.Input / RawInput: sticks first, then triggers.
MODERN_XBOX_MAPPING = XINPUT_MAPPING.replace("lefttrigger:a2", "lefttrigger:a4").replace(
    "rightx:a3", "rightx:a2").replace("righty:a4", "righty:a3")


def pairs(text):
    return tuple(tuple(item.split(":", 1)) for item in text.split(","))


def test_xinput_mapping_matches_the_xinput_preset():
    resolved = layouts.resolve("g", 6, 11, 1, {}, pairs(XINPUT_MAPPING))
    assert resolved["base"] == layouts.SDL_MAPPING
    assert resolved["bindings"] == layouts.PRESETS["xinput"]["bindings"]


def test_modern_xbox_axis_order_comes_from_sdl_not_the_preset():
    # Regression: a hat made auto-detect pick the XInput preset, so LT read the right
    # stick's X axis (half pressed at rest) and the right stick's Y read LT (stuck up).
    guessed = layouts.resolve("g", 6, 11, 1, {})
    assert guessed["base"] == "xinput" and guessed["bindings"]["lt"]["index"] == 2
    resolved = layouts.resolve("g", 6, 11, 1, {}, pairs(MODERN_XBOX_MAPPING))
    b = resolved["bindings"]
    assert resolved["base"] == layouts.SDL_MAPPING
    assert (b["lt"]["index"], b["rt"]["index"], b["right_x"]["index"], b["right_y"]["index"]) == (4, 5, 2, 3)
    assert b == layouts.PRESETS["xbox_modern"]["bindings"]


def test_manual_preset_and_custom_bindings_win_over_sdl():
    mapping = pairs(MODERN_XBOX_MAPPING)
    manual = layouts.resolve("g", 6, 11, 1, {"g": {"preset": "xinput"}}, mapping)
    assert manual["base"] == "xinput" and manual["bindings"]["lt"]["index"] == 2
    custom = layouts.resolve("g", 6, 11, 1, {"g": {"bindings": {"lt": {"kind": "button", "index": 6}}}},
                             mapping)
    assert custom["base"] == layouts.SDL_MAPPING and custom["bindings"]["lt"] == {"kind": "button", "index": 6}


def test_half_axis_triggers_and_inverted_axes():
    b = layouts.bindings_from_sdl_mapping({"leftx": "a0", "lefty": "a1~", "lefttrigger": "+a2",
                                           "righttrigger": "-a2", "dpup": "+a5", "a": "b0"})
    assert b["left_y"] == {"kind": "axis", "index": 1, "invert": True}
    assert b["lt"] == {"kind": "axis", "index": 2, "rest": 0.0, "invert": False}
    assert b["rt"] == {"kind": "axis", "index": 2, "rest": 0.0, "invert": True}
    assert b["dpad_up"] == {"kind": "axis", "index": 5, "sign": 1}
    axes = (0.0, 0.0, -0.8, 0.0, 0.0, 0.0)  # shared Z axis pushed by the right trigger
    assert layouts.read_trigger(b["lt"], axes, (), (), {}) == (-0.8, 0.0)  # clamps to 0 later
    assert layouts.read_trigger(b["rt"], axes, (), (), {}) == (0.8, -0.0)
    assert layouts.normalize_binding(b["rt"]) == b["rt"]


def test_unusable_mappings_fall_back_to_presets():
    assert layouts.bindings_from_sdl_mapping({}) == {}
    assert layouts.bindings_from_sdl_mapping({"a": "b0"}) == {}  # no left stick
    junk = layouts.bindings_from_sdl_mapping({"leftx": "a0", "lefty": "a1", "rightx": "+a3",
                                              "x": "q9", "y": "h0.3", "b": "bX"})
    assert junk["right_x"] is None and junk["x"] is None and junk["y"] is None and junk["b"] is None
    assert layouts.resolve("g", 6, 16, 0, {}, ())["base"] == "sdl"


def test_controls_sdl_omits_are_filled_without_reusing_its_inputs():
    # SDL maps the buttons to game-controller order but leaves the hat alone.
    mapping = {"a": "b0", "b": "b1", "x": "b2", "y": "b3", "back": "b4", "guide": "b5",
               "start": "b6", "leftstick": "b7", "rightstick": "b8", "leftshoulder": "b9",
               "rightshoulder": "b10", "leftx": "a0", "lefty": "a1", "rightx": "a2",
               "righty": "a3", "lefttrigger": "a4", "righttrigger": "a5"}
    b = layouts.resolve("g", 6, 11, 1, {}, mapping)["bindings"]
    assert b["dpad_up"] == {"kind": "hat", "index": 0, "dir": "up"}  # filled from the preset
    assert b["guide"] == {"kind": "button", "index": 5}  # from SDL, not the preset's b10
