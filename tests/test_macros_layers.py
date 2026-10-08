"""Engine behaviour of back paddles, macros and modifier layers (fake pad, manual ticks)."""

import copy

from app import defaults, macros, model
from tests.conftest import Rig

A, X, LB, RB, GUIDE = 0, 2, 4, 5, 10
LT, RT = 2, 5  # XInput axes of the fake pad
TICK_MS = 4


def empty_profile() -> dict:
    return copy.deepcopy(defaults.template(defaults.EMPTY))


def key(name: str, mode: str = "hold") -> dict:
    return model.make_slot(model.key_action(name, mode=mode))


def macro_slot(steps: list, loop: bool = False) -> dict:
    return model.make_slot(model.macro_action(steps, loop=loop))


def keys_sent(rig: Rig) -> list[tuple]:
    return [(name, down) for kind, name, down in rig.sent("key")]


# --- back paddles -----------------------------------------------------------------

def test_paddle_from_sdl_mapping_drives_its_own_slot():
    profile = empty_profile()
    profile["buttons"]["p1"] = key("f1")
    profile["buttons"]["guide"] = key("f2")
    rig = Rig(profile, (("leftx", "a0"), ("lefty", "a1"), ("paddle1", "b10")))
    rig.dm.buttons[GUIDE] = 1  # raw button 10 is the paddle here, not the guide button
    rig.tick()
    assert rig.held == ["f1"]
    snap_layout = rig.engine._devices[7].layout["bindings"]
    assert snap_layout["guide"] is None and snap_layout["p1"] == {"kind": "button", "index": 10}


# --- macros ------------------------------------------------------------------------

def test_macro_runs_to_the_end_with_its_timing_after_a_quick_press():
    profile = empty_profile()
    profile["buttons"]["a"] = macro_slot(macros.tap_steps(["ctrl", "c"], gap_ms=50))
    rig = Rig(profile)
    rig.dm.buttons[A] = 1
    rig.tick()
    rig.dm.buttons[A] = 0
    rig.tick()
    assert keys_sent(rig) == [("ctrl", True), ("c", True)]
    rig.tick(40 // TICK_MS)  # about 48 ms after the press
    assert rig.held == ["c", "ctrl"]
    rig.tick(3)
    assert keys_sent(rig)[2:] == [("c", False), ("ctrl", False)] and rig.held == []
    assert not rig.engine._macros


def test_repeating_macro_loops_while_held_and_stops_on_release():
    steps = [macros.key_step("key_down", "a"), macros.wait_step(20),
             macros.key_step("key_up", "a"), macros.wait_step(20)]
    profile = empty_profile()
    profile["buttons"]["x"] = macro_slot(steps, loop=True)
    rig = Rig(profile)
    rig.dm.buttons[X] = 1
    rig.tick(200 // TICK_MS + 2)
    downs = keys_sent(rig).count(("a", True))
    assert 4 <= downs <= 6
    rig.tick(1)
    while "a" not in rig.held:  # release in the middle of a key-down
        rig.tick(1)
    rig.dm.buttons[X] = 0
    rig.tick()
    assert rig.held == [] and keys_sent(rig)[-1] == ("a", False) and not rig.engine._macros
    rig.backend.log.clear()
    rig.tick(50)
    assert not rig.sent()


def test_retrigger_while_a_macro_runs_is_ignored():
    profile = empty_profile()
    profile["buttons"]["a"] = macro_slot(macros.tap_steps(["q"], gap_ms=100))
    rig = Rig(profile)
    for _ in range(3):
        rig.dm.buttons[A] = 1
        rig.tick()
        rig.dm.buttons[A] = 0
        rig.tick()
    rig.tick(40)
    assert keys_sent(rig) == [("q", True), ("q", False)]


def test_keys_a_macro_leaves_down_are_released_when_it_ends():
    profile = empty_profile()
    profile["buttons"]["a"] = macro_slot([macros.key_step("key_down", "shift"),
                                          macros.button_step("button_down", "right")])
    rig = Rig(profile)
    rig.dm.buttons[A] = 1
    rig.tick()
    assert rig.held == [] and ("shift", True) in keys_sent(rig) and ("shift", False) in keys_sent(rig)
    assert rig.sent("btn") == [("btn", "right", True), ("btn", "right", False)]


def test_macros_on_short_tap_and_release_slots():
    profile = empty_profile()
    profile["buttons"]["a"] = model.make_slot(
        model.key_action("h"), hold_ms=200,
        tap=model.macro_action(macros.tap_steps(["t"])),
        release=model.macro_action(macros.tap_steps(["u"]), loop=True))
    rig = Rig(model.normalize_profile(profile))
    assert rig.engine._profile["buttons"]["a"]["release"]["loop"] is False
    rig.dm.buttons[A] = 1
    rig.tick(5)
    rig.dm.buttons[A] = 0
    rig.tick(20)
    assert keys_sent(rig) == [("t", True), ("u", True), ("t", False), ("u", False)]


def test_disconnect_pause_and_profile_swap_stop_running_macros():
    steps = [macros.key_step("key_down", "w"), macros.wait_step(1000), macros.key_step("key_up", "w")]
    profile = empty_profile()
    profile["buttons"]["a"] = macro_slot(steps)
    for stop in ("disconnect", "pause", "swap"):
        rig = Rig(profile)
        rig.dm.buttons[A] = 1
        rig.tick(2)
        assert rig.held == ["w"] and rig.engine._macros
        if stop == "disconnect":
            rig.dm.disconnect()
        elif stop == "pause":
            rig.engine.pause("dialog")
        else:
            rig.engine.set_profile(empty_profile())
        rig.tick()
        assert rig.held == [] and not rig.engine._macros, stop


# --- modifier layers -----------------------------------------------------------------

def layered_profile() -> dict:
    profile = empty_profile()
    profile["buttons"]["x"] = key("r")
    profile["buttons"]["a"] = key("space")
    profile["buttons"]["rb"] = model.make_slot(hold_ms=200, tap=model.key_action("t", mode="tap"))
    profile["triggers"]["rt"]["zones"]["soft"] = model.make_slot(model.mouse_button_action("left"))
    rt = model.new_layer("Cross right", ["trigger:rt"])
    rt["slots"]["button:x"] = key("1")
    both = model.new_layer("Both", ["trigger:lt", "trigger:rt"])
    both["slots"]["button:x"] = key("2")
    rb = model.new_layer("Bumper", ["button:rb"])
    rb["slots"]["button:x"] = key("9")
    profile["layers"] = [rt, both, rb]
    return model.normalize_profile(profile)


def test_layer_override_replaces_only_its_own_slots():
    rig = Rig(layered_profile())
    rig.dm.buttons[X] = 1
    rig.tick()
    assert rig.held == ["r"]
    rig.dm.buttons[X] = 0
    rig.tick()
    rig.dm.axes[RT] = 1.0
    rig.tick()
    assert rig.held == ["mouse:left"]  # the modifier keeps its own base mapping
    rig.dm.buttons[X], rig.dm.buttons[A] = 1, 1
    rig.tick()
    assert rig.held == ["1", "space", "mouse:left"]  # A has no override: base mapping
    rig.engine._publish(rig.now, False)
    assert rig.engine.snapshot()["preview"][7]["layer"] == 0


def test_layer_is_latched_per_press():
    rig = Rig(layered_profile())
    rig.dm.buttons[X] = 1
    rig.tick()
    rig.dm.axes[RT] = 1.0
    rig.tick(3)
    assert "r" in rig.held and "1" not in rig.held  # pressed before the modifier: stays base
    rig.dm.buttons[X] = 0
    rig.tick()
    assert "r" not in rig.held
    rig.dm.buttons[X] = 1
    rig.tick()
    assert "1" in rig.held
    rig.dm.axes[RT] = -1.0  # let go of the modifier first
    rig.tick(3)
    assert rig.held == ["1"]
    rig.dm.buttons[X] = 0
    rig.tick()
    assert rig.held == []


def test_layer_with_more_modifiers_wins():
    rig = Rig(layered_profile())
    rig.dm.axes[RT] = rig.dm.axes[LT] = 1.0
    rig.tick()
    rig.dm.buttons[X] = 1
    rig.tick()
    assert "2" in rig.held and "1" not in rig.held


def test_used_modifier_skips_its_short_tap():
    rig = Rig(layered_profile())
    rig.dm.buttons[RB] = 1
    rig.tick()
    rig.dm.buttons[X] = 1
    rig.tick()
    assert rig.held == ["9"]
    rig.dm.buttons[X] = 0
    rig.tick()
    rig.dm.buttons[RB] = 0
    rig.tick(10)
    assert ("t", True) not in keys_sent(rig)
    rig.dm.buttons[RB] = 1  # a quick tap on its own still fires the tap action
    rig.tick()
    rig.dm.buttons[RB] = 0
    rig.tick()
    assert ("t", True) in keys_sent(rig)
