"""Engine behaviour with a fake controller and fake output (deterministic manual ticks)."""

import copy

from app import defaults, model

A, X, START = 0, 2, 7
LEFT_X, LEFT_Y, RIGHT_X, RT = 0, 1, 3, 5


def test_button_hold_press_and_release(make_rig):
    rig = make_rig()
    rig.dm.buttons[A] = 1
    rig.tick()
    assert rig.held == ["space"]
    rig.dm.buttons[A] = 0
    rig.tick()
    assert rig.held == [] and rig.sent("key") == [("key", "space", True), ("key", "space", False)]


def test_press_and_release_between_two_polls_is_not_dropped(make_rig):
    from app.gamepad import DigitalEvent

    rig = make_rig()
    rig.dm.events = [DigitalEvent(7, "button", A, 1), DigitalEvent(7, "button", A, 0)]
    rig.tick()
    assert rig.sent("key") == [("key", "space", True), ("key", "space", False)]


def test_wasd_diagonal_presses_both_cardinals_without_repress(make_rig):
    rig = make_rig()
    rig.dm.axes[LEFT_X], rig.dm.axes[LEFT_Y] = 0.7, -0.7
    rig.tick(5)
    assert {"w", "d"} <= set(rig.held)
    rig.backend.log.clear()
    rig.dm.axes[LEFT_X], rig.dm.axes[LEFT_Y] = 1.0, 0.0
    rig.tick(3)
    assert ("key", "w", False) in rig.backend.log
    assert ("key", "d", True) not in rig.backend.log  # d stayed down the whole time
    assert "shift" in rig.held  # full deflection reaches the outer ring (sprint)


def test_disconnect_while_held_releases_everything(make_rig):
    rig = make_rig()
    rig.dm.buttons[A] = 1
    rig.dm.axes[LEFT_X] = 1.0
    rig.tick(3)
    assert rig.held
    rig.dm.disconnect()
    rig.tick()
    assert rig.held == []
    assert not rig.engine._devices


def test_trigger_jitter_around_threshold_clicks_once(make_rig):
    rig = make_rig()
    for value in (-0.69, -0.71, -0.69, -0.72, -0.70, -0.68):  # wobble around 15 % activation
        rig.dm.axes[RT] = value
        rig.tick()
    assert rig.sent("btn") == [("btn", "left", True)]
    rig.dm.axes[RT] = -1.0
    rig.tick()
    assert rig.sent("btn")[-1] == ("btn", "left", False)


def test_mouse_look_moves_relative(make_rig):
    rig = make_rig()
    rig.dm.axes[RIGHT_X] = 1.0
    rig.tick(10)
    moves = rig.sent("move")
    assert moves and all(m[1] > 0 and m[2] == 0 for m in moves)
    rig.backend.log.clear()
    rig.dm.axes[RIGHT_X] = 0.0
    rig.tick(3)
    assert not rig.sent("move")


def test_tap_mode_releases_after_minimum_duration(make_rig):
    rig = make_rig()
    rig.dm.buttons[START] = 1
    rig.tick()
    rig.dm.buttons[START] = 0
    rig.tick()
    assert rig.sent("key") == [("key", "esc", True)]
    rig.tick(10)
    assert rig.sent("key")[-1] == ("key", "esc", False)


def test_hold_threshold_separates_tap_from_long_press(make_rig):
    rig = make_rig()
    profile = copy.deepcopy(defaults.template(defaults.FPS))
    profile["buttons"]["x"] = model.make_slot(
        model.key_action("r"), hold_ms=300, tap=model.key_action("e", mode="tap"),
        release=model.key_action("f", mode="tap"))
    rig.engine.set_profile(profile)
    rig.tick()
    rig.dm.buttons[X] = 1
    rig.tick(10)  # 40 ms, well under 300 ms
    rig.dm.buttons[X] = 0
    rig.tick()
    assert ("key", "e", True) in rig.backend.log and ("key", "r", True) not in rig.backend.log
    rig.tick(20)
    rig.backend.log.clear()
    rig.dm.buttons[X] = 1
    rig.tick(100)  # 400 ms
    assert ("key", "r", True) in rig.backend.log
    rig.dm.buttons[X] = 0
    rig.tick()
    assert ("key", "r", False) in rig.backend.log and ("key", "f", True) in rig.backend.log


def test_rapid_profile_switches_release_old_keys_and_apply_latest(make_rig):
    rig = make_rig()
    rig.dm.buttons[A] = 1
    rig.tick()
    assert "space" in rig.held
    for _ in range(5):
        rig.engine.set_profile(defaults.template(defaults.DESKTOP))
    rig.engine.set_profile(defaults.template(defaults.EMPTY))
    rig.tick()
    assert rig.held == []
    rig.tick(3)
    assert rig.held == []  # Empty maps nothing; the held A does not leak a stale key


def test_profile_switch_reapplies_held_button_under_new_map(make_rig):
    rig = make_rig()
    rig.dm.buttons[A] = 1
    rig.tick()
    rig.engine.set_profile(defaults.template(defaults.DESKTOP))
    rig.tick(2)
    assert rig.held == ["enter"]


def test_modal_pause_releases_and_resume_restores(make_rig):
    rig = make_rig(defaults.DESKTOP)
    rig.dm.buttons[A] = 1
    rig.tick()
    assert rig.held == ["enter"]
    rig.engine.pause("dialog")
    rig.tick()
    assert rig.held == []
    rig.tick(3)
    assert rig.held == []
    rig.engine.resume("dialog")
    rig.tick()
    assert rig.held == ["enter"]


def test_nested_pauses_need_matching_resumes(make_rig):
    rig = make_rig()
    rig.engine.pause("dialog")
    rig.engine.pause("dialog")
    rig.engine.resume("dialog")
    assert rig.engine.is_paused()
    rig.engine.resume("dialog")
    assert not rig.engine.is_paused()


def test_dpad_cardinals_in_desktop_profile(make_rig):
    rig = make_rig(defaults.DESKTOP)
    rig.dm.hats[0] = (1, 1)
    rig.tick()
    assert {"up", "right"} <= set(rig.held)
    rig.dm.hats[0] = (0, 0)
    rig.tick()
    assert rig.held == []


def test_calibration_stores_offsets_and_keeps_mappings(make_rig):
    rig = make_rig()
    result = {}
    rig.engine.on_calibrated = result.update
    rig.dm.axes[LEFT_X], rig.dm.axes[LEFT_Y] = 0.05, -0.04
    rig.engine.request_calibration(7)
    rig.tick(600)  # 2.4 s of simulated time
    assert result["ok"] and abs(result["axes"][0] - 0.05) < 1e-6
    assert result["guid"] == rig.dm.info.guid and not result["warnings"]


def test_calibration_rejects_a_touched_stick(make_rig):
    rig = make_rig()
    result = {}
    rig.engine.on_calibrated = result.update
    rig.dm.axes[LEFT_X] = 0.8
    rig.engine.request_calibration(7)
    rig.tick(600)
    assert 0 not in result["axes"] and result["warnings"]


def test_snapshot_reports_devices_and_pause_state(make_rig):
    rig = make_rig()
    rig.engine.set_user_paused(True)
    rig.tick()
    rig.engine._publish(rig.now, True)
    snap = rig.engine.snapshot()
    assert snap["devices"][0]["name"] == "Fake Pad" and snap["user_paused"] and snap["paused"]


def test_sdl_mapping_reads_triggers_and_sticks_from_the_right_axes(make_rig):
    # Xbox pad via Windows.Gaming.Input: axes are LX, LY, RX, RY, LT, RT plus a D-pad hat.
    mapping = (("a", "b0"), ("leftx", "a0"), ("lefty", "a1"), ("rightx", "a2"), ("righty", "a3"),
               ("lefttrigger", "a4"), ("righttrigger", "a5"), ("dpup", "h0.1"))
    rig = make_rig(defaults.DESKTOP, mapping)
    rig.dm.axes[:] = [0.0, 0.0, 0.0, 0.0, -1.0, -1.0]  # everything at rest
    rig.tick(5)
    rig.backend.log.clear()  # drop output from the fake pad's XInput-style start values
    rig.tick(5)
    assert rig.held == [] and not rig.sent("move")
    rig.dm.axes[4] = 1.0  # pull LT
    rig.tick(3)
    assert rig.held == ["mouse:right"] and not rig.sent("move")
    rig.dm.axes[4], rig.dm.axes[3] = -1.0, -1.0  # release LT, right stick up
    rig.tick(5)
    assert rig.held == [] and all(m[2] < 0 for m in rig.sent("move"))
