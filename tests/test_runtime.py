"""Threaded engine lifecycle, the real pygame device manager (no hardware), logging, paths."""

import logging
import time

import pytest

from app import defaults, layouts, logging_setup, paths
from app.engine import MappingEngine
from app.gamepad import MAX_DEVICES, DeviceManager
from app.injector import Injector
from tests.conftest import FakeBackend, FakeDeviceManager


def test_engine_thread_runs_and_releases_everything_on_stop():
    backend, holder = FakeBackend(), {}

    def dm_factory(on_added, on_removed):
        holder["dm"] = FakeDeviceManager(on_added, on_removed)
        holder["dm"].connect()
        return holder["dm"]

    engine = MappingEngine(injector_factory=lambda: Injector(backend), device_manager_factory=dm_factory)
    engine.set_polling_rate(500)
    engine.set_profile(defaults.template(defaults.FPS))
    engine.start()
    try:
        deadline = time.monotonic() + 3
        while not engine.snapshot()["devices"] and time.monotonic() < deadline:
            time.sleep(0.01)
        holder["dm"].buttons[0] = 1
        while "space" not in engine.snapshot()["held"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert "space" in engine.snapshot()["held"]
        assert engine.snapshot()["stats"]["target_hz"] == 500
    finally:
        engine.stop()
    assert backend.log[-1] == ("key", "space", False)  # exit released the held key
    assert engine._thread is None


def test_engine_survives_a_failing_device_manager():
    def broken(_added, _removed):
        raise RuntimeError("no SDL")

    engine = MappingEngine(injector_factory=lambda: Injector(FakeBackend()), device_manager_factory=broken)
    engine.start()
    deadline = time.monotonic() + 3
    while not engine.snapshot()["error"] and time.monotonic() < deadline:
        time.sleep(0.01)
    engine.stop()
    assert "no SDL" in engine.snapshot()["error"]


def test_real_device_manager_without_hardware():
    pygame = pytest.importorskip("pygame")
    added, removed = [], []
    manager = DeviceManager(added.append, removed.append)
    manager.start()
    try:
        assert manager.poll(time.perf_counter()) == []
        assert manager.devices() == [] and manager.read(0) is None
    finally:
        manager.stop()
    assert not pygame.get_init() and MAX_DEVICES == 4 and not added and not removed


def test_debug_log_is_written_and_rotates_under_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    logging_setup.configure(debug=True)
    try:
        logging_setup.log.debug("hello %s", "world")
        logging_setup.debug_throttled("k", 60, "first")
        logging_setup.debug_throttled("k", 60, "suppressed")
        for handler in logging_setup.log.handlers:
            handler.flush()
        text = (paths.log_dir() / "gamepad-mapper.log").read_text(encoding="utf-8")
        assert "hello world" in text and "first" in text and "suppressed" not in text
        assert paths.log_dir() == tmp_path / "GamepadMapper" / "logs"
    finally:
        logging_setup.set_debug(False)
    assert logging_setup.log.level == logging.WARNING


def test_atomic_write_replaces_file_and_leaves_no_temp(tmp_path):
    target = tmp_path / "sub" / "f.json"
    paths.atomic_write_text(target, "one")
    paths.atomic_write_text(target, "two")
    assert target.read_text() == "two" and [p.name for p in target.parent.iterdir()] == ["f.json"]


def _bundled_sdl():
    """ctypes handle to the SDL2 library pygame already loaded, or None."""
    import ctypes
    import glob
    import os

    pygame = pytest.importorskip("pygame")
    base = os.path.dirname(pygame.__file__)
    patterns = ("SDL2.dll", os.path.join(os.pardir, "pygame.libs", "libSDL2-2*.so*"),
                os.path.join(".dylibs", "libSDL2*.dylib"))
    for pattern in patterns:
        found = glob.glob(os.path.join(base, pattern))
        if found:
            return ctypes.CDLL(found[0])
    return None


def test_virtual_controller_resolves_through_sdl_mapping():
    """A real SDL device: raw axes sticks-first (LX, LY, RX, RY, LT, RT) and back paddles.

    One device only: SDL caches a controller mapping per GUID and all plain virtual pads
    share a GUID, so a second virtual pad would inherit the first one's mapping.
    """
    import ctypes

    sdl = _bundled_sdl()
    if sdl is None or not hasattr(sdl, "SDL_JoystickSetVirtualButton"):
        pytest.skip("pygame's SDL library is not reachable through ctypes here")
    added: list = []
    manager = DeviceManager(added.append, lambda _info: None)
    manager.start()
    sdl.SDL_JoystickOpen.restype = ctypes.c_void_p
    sdl.SDL_JoystickSetVirtualButton.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_uint8)
    sdl.SDL_JoystickClose.argtypes = (ctypes.c_void_p,)
    sdl.SDL_JoystickDetachVirtual.argtypes = (ctypes.c_int,)
    try:
        index = sdl.SDL_JoystickAttachVirtual(1, 6, 21, 0)  # SDL_JOYSTICK_TYPE_GAMECONTROLLER
        assert index >= 0
        manager.poll(time.perf_counter())
        assert added, "virtual controller was not picked up"
        info = added[0]
        mapping = dict(info.sdl_mapping)
        assert mapping["lefttrigger"] == "a4" and mapping["righty"] == "a3"
        bindings = layouts.resolve(info.guid, info.num_axes, info.num_buttons, info.num_hats,
                                   {}, info.sdl_mapping)["bindings"]
        assert bindings["lt"]["index"] == 4 and bindings["right_y"]["index"] == 3
        # SDL numbers the paddles P1, P3, P2, P4 (raw b16-b19 on its virtual pad).
        assert [bindings[p]["index"] for p in ("p1", "p3", "p2", "p4")] == [16, 17, 18, 19]
        handle = sdl.SDL_JoystickOpen(index)
        sdl.SDL_JoystickSetVirtualButton(handle, 18, 1)
        manager.poll(time.perf_counter())
        raw = manager.read(info.instance_id)
        pressed = [p for p in ("p1", "p2", "p3", "p4")
                   if layouts.read_digital(bindings[p], raw.axes, raw.buttons, raw.hats)]
        assert pressed == ["p2"]
        sdl.SDL_JoystickClose(handle)
        sdl.SDL_JoystickDetachVirtual(index)
    finally:
        manager.stop()
