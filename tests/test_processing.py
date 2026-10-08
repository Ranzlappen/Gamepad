from app import processing
from app.model import DEFAULT_DEADZONE, new_profile


def test_sector_boundaries_and_hysteresis():
    assert processing.sector_for(0, 8) == "n"
    assert processing.sector_for(44, 8) == "ne"
    assert processing.sector_for(23, 8) == "ne"
    # Past the 22.5 degree edge but inside the 6 degree hysteresis band: stay in "n".
    assert processing.sector_for(25, 8, previous="n") == "n"
    assert processing.sector_for(29, 8, previous="n") == "ne"
    assert processing.sector_for(100, 4) == "e"


def test_diagonal_modes():
    assert processing.zones_for_sector("ne", "combined") == ("ne",)
    assert processing.zones_for_sector("ne", "cardinals") == ("n", "e")
    assert processing.zones_for_sector("n", "cardinals") == ("n",)
    assert processing.dpad_zones(True, False, False, True, "combined") == ("ne",)
    assert processing.dpad_zones(True, False, False, True, "cardinals") == ("n", "e")
    assert processing.dpad_zones(False, False, False, False, "combined") == ()


def test_schmitt_trigger_absorbs_jitter():
    state, flips = False, 0
    for value in (0.151, 0.139, 0.151, 0.14, 0.152):  # wobble around a 0.15 threshold
        new = processing.schmitt(state, value, 0.15)
        flips += new != state
        state = new
    assert flips == 1 and state is True
    assert processing.schmitt(True, 0.10, 0.15) is False  # a real release still releases


def test_drift_filter_recentres_after_delay_and_wakes_on_movement():
    f = processing.DriftFilter()
    assert f.apply(0.05, 0.08, 0.3, 0.0) == 0.05
    assert f.apply(0.05, 0.08, 0.3, 0.2) == 0.05  # not long enough yet
    assert f.apply(0.05, 0.08, 0.3, 0.31) == 0.0
    assert f.apply(0.07, 0.08, 0.3, 0.5) == 0.0  # stays snapped while below the threshold
    assert f.apply(0.2, 0.08, 0.3, 0.6) == 0.2  # real input wakes the axis
    assert f.apply(0.05, 0.0, 0.3, 5.0) == 0.05  # threshold 0 disables the filter


def test_stick_processor_deadzone_zones_and_outer_ring():
    cfg = new_profile("t")["sticks"]["left"]
    proc = processing.StickProcessor()
    args = (cfg, 0.0, 0.3, 1.0)
    inside = proc.update(0.1, 0.05, 0.0, 0.0, *args)
    assert not inside.active and inside.zones == frozenset() and inside.processed == (0.0, 0.0)
    right = proc.update(0.5, 0.0, 0.0, 0.0, *args)
    assert right.active and right.zones == {"e"} and 0 < right.strength < 1
    edge = proc.update(1.0, 0.0, 0.0, 0.0, *args)
    assert edge.zones == {"e", "outer"} and edge.strength == 1.0
    assert cfg["deadzone"] == DEFAULT_DEADZONE


def test_stick_calibration_offset_is_subtracted():
    cfg = new_profile("t")["sticks"]["left"]
    proc = processing.StickProcessor()
    result = proc.update(0.10, 0.0, 0.10, 0.0, cfg, 0.0, 0.3, 1.0)  # resting at +0.10
    assert not result.active


def test_stick_mouse_mode_has_no_zones_but_outer():
    cfg = new_profile("t")["sticks"]["right"]
    cfg["mode"] = "mouse"
    result = processing.StickProcessor().update(1.0, 0.0, 0.0, 0.0, cfg, 0.0, 0.3, 1.0)
    assert result.zones == {"outer"}


def test_trigger_response_and_zones():
    assert processing.trigger_response(0.05, 0.1, 0.9, "linear", 2.0) == 0.0
    assert processing.trigger_response(0.5, 0.1, 0.9, "linear", 2.0) == 0.5
    assert abs(processing.trigger_response(0.5, 0.1, 0.9, "curved", 2.0) - 0.25) < 1e-9
    assert processing.trigger_response(0.95, 0.1, 0.9, "linear", 2.0) == 1.0
    cfg = new_profile("t")["triggers"]["lt"]
    proc = processing.TriggerProcessor()
    assert proc.update(-1.0, -1.0, cfg, 0.0, 0.3, 0.0).zones == frozenset()
    assert proc.update(0.0, -1.0, cfg, 0.0, 0.3, 0.1).zones == {"soft"}  # 50 % pressed
    assert proc.update(1.0, -1.0, cfg, 0.0, 0.3, 0.2).zones == {"soft", "full"}


def test_accel_multiplier_is_capped():
    assert processing.accel_multiplier(0.0, 5.0) == 1.0
    assert processing.accel_multiplier(1.0, 1.0) == 2.0
    assert processing.accel_multiplier(5.0, 10.0) == processing.MAX_ACCEL_MULTIPLIER
