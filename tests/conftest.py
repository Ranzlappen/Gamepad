"""Shared fixtures: a fake device manager and output backend drive the real engine."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from app import defaults  # noqa: E402
from app.engine import MappingEngine  # noqa: E402
from app.gamepad import DeviceInfo, RawState  # noqa: E402
from app.injector import Injector  # noqa: E402

GUID = "030000005e040000e002000000007801"


class FakeBackend:
    """Records what would have been sent to the OS."""

    def __init__(self) -> None:
        self.log: list[tuple] = []

    def key(self, name: str, down: bool) -> None:
        self.log.append(("key", name, down))

    def button(self, name: str, down: bool) -> None:
        self.log.append(("btn", name, down))

    def move(self, dx: int, dy: int) -> None:
        self.log.append(("move", dx, dy))


class FakeDeviceManager:
    """One scripted Xbox-style pad (6 axes, 11 buttons, 1 hat); no SDL involved."""

    def __init__(self, on_added, on_removed) -> None:
        self.on_added, self.on_removed = on_added, on_removed
        self.info = DeviceInfo(7, 1, "Fake Pad", GUID, 6, 11, 1)
        self.axes = [0.0, 0.0, -1.0, 0.0, 0.0, -1.0]
        self.buttons = [0] * 11
        self.hats = [(0, 0)]
        self.events: list = []
        self.connected = False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.disconnect()

    def connect(self) -> None:
        self.connected = True
        self.on_added(self.info)

    def disconnect(self) -> None:
        if self.connected:
            self.connected = False
            self.on_removed(self.info)

    def poll(self, _now: float) -> list:
        events, self.events = self.events, []
        return events

    def read(self, _instance_id: int):
        if not self.connected:
            return None
        return RawState(tuple(self.axes), tuple(self.buttons), tuple(self.hats))


class Rig:
    """Engine + fakes with manual ticking (no thread), so tests are deterministic."""

    def __init__(self, profile: dict) -> None:
        self.backend = FakeBackend()
        self.engine = MappingEngine()
        self.engine._injector = Injector(self.backend)
        self.dm = FakeDeviceManager(self.engine._on_device_added, self.engine._on_device_removed)
        self.engine._dm = self.dm
        self.now = 100.0
        self.engine.set_profile(profile)
        self.tick()
        self.dm.connect()
        self.tick()

    def tick(self, n: int = 1, dt: float = 0.004) -> None:
        for _ in range(n):
            self.now += dt
            self.engine._tick(self.now, dt)

    @property
    def held(self) -> list[str]:
        return self.engine._injector.held()

    def sent(self, kind: str | None = None) -> list[tuple]:
        return [e for e in self.backend.log if kind is None or e[0] == kind]


@pytest.fixture
def make_rig():
    return lambda name=defaults.FPS: Rig(defaults.template(name))
