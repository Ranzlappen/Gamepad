"""pygame joystick enumeration, hot-plug handling and raw state reads.

Every pygame call happens on the mapping-engine thread: SDL pumps the Windows
message queue of the thread that initialised it, so init, pump, reads and
quit must all share that one thread.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass

import pygame

from app.logging_setup import debug_throttled, log

MAX_DEVICES = 4
SCAN_INTERVAL_S = 0.5


@dataclass(frozen=True)
class DeviceInfo:
    instance_id: int
    player: int
    name: str
    guid: str
    num_axes: int
    num_buttons: int
    num_hats: int
    # SDL's game-controller mapping as sorted (key, value) pairs; () if SDL does not know the pad.
    sdl_mapping: tuple = ()


def _sdl_mapping(index: int) -> tuple:
    """SDL's own mapping of this device's raw buttons/axes/hats to a standard gamepad.

    SDL knows most pads (XInput, Windows.Gaming.Input, RawInput and HIDAPI drivers plus its
    built-in controller database), and the raw index order differs between those drivers,
    so this is far more reliable than guessing a preset. Opening the game controller only
    adds a reference to the already-open joystick; it is closed again right away.
    """
    try:
        from pygame._sdl2 import controller

        if not controller.get_init():
            controller.init()
        if not controller.is_controller(index):
            return ()
        pad = controller.Controller(index)
        try:
            mapping = pad.get_mapping()
        finally:
            pad.quit()
            with contextlib.suppress(AttributeError, ValueError):
                controller.Controller._controllers.remove(pad)  # pygame keeps every pad here
    except Exception as exc:  # private pygame API: never let it break device handling
        log.debug("No SDL controller mapping for joystick %d: %s", index, exc)
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in mapping.items()))


@dataclass(frozen=True)
class RawState:
    axes: tuple
    buttons: tuple
    hats: tuple


@dataclass(frozen=True)
class DigitalEvent:
    """A button or hat change, kept in arrival order so fast taps are never lost."""
    instance_id: int
    kind: str  # "button" | "hat"
    index: int
    value: object  # 0/1 for buttons, (x, y) for hats


class DeviceManager:
    def __init__(self, on_added: Callable[[DeviceInfo], None],
                 on_removed: Callable[[DeviceInfo], None]) -> None:
        self._on_added = on_added
        self._on_removed = on_removed
        self._joysticks: dict[int, pygame.joystick.JoystickType] = {}
        self._infos: dict[int, DeviceInfo] = {}
        self._ignored: set[int] = set()  # devices with zero axes and zero buttons
        self._known_count = -1
        self._next_scan = 0.0
        self._rescan_requested = True

    def start(self) -> None:
        # The event queue needs the video subsystem; no window is ever created.
        pygame.display.init()
        pygame.joystick.init()

    def stop(self) -> None:
        for instance_id in list(self._joysticks):
            self._remove(instance_id)
        pygame.quit()

    def devices(self) -> list[DeviceInfo]:
        return sorted(self._infos.values(), key=lambda info: info.player)

    def poll(self, now: float) -> list[DigitalEvent]:
        """Pump SDL, handle hot-plug, and return this tick's digital events in order."""
        digital: list[DigitalEvent] = []
        for event in pygame.event.get():
            if event.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
                if event.instance_id in self._joysticks:
                    digital.append(DigitalEvent(event.instance_id, "button", event.button,
                                                int(event.type == pygame.JOYBUTTONDOWN)))
            elif event.type == pygame.JOYHATMOTION:
                if event.instance_id in self._joysticks:
                    digital.append(DigitalEvent(event.instance_id, "hat", event.hat,
                                                tuple(event.value)))
            elif event.type == pygame.JOYDEVICEADDED:
                self._rescan_requested = True
            elif event.type == pygame.JOYDEVICEREMOVED:
                # Release this device's keys right away instead of waiting for the next scan.
                self._remove(event.instance_id)
                self._ignored.discard(event.instance_id)
                self._rescan_requested = True
        if self._rescan_requested or now >= self._next_scan:
            self._next_scan = now + SCAN_INTERVAL_S
            count = pygame.joystick.get_count()
            if self._rescan_requested or count != self._known_count:
                self._rescan_requested = False
                self._rescan(count)
        return digital

    def read(self, instance_id: int) -> RawState | None:
        joystick = self._joysticks.get(instance_id)
        info = self._infos.get(instance_id)
        if joystick is None or info is None:
            return None
        try:
            return RawState(
                tuple(joystick.get_axis(i) for i in range(info.num_axes)),
                tuple(joystick.get_button(i) for i in range(info.num_buttons)),
                tuple(joystick.get_hat(i) for i in range(info.num_hats)),
            )
        except pygame.error:
            # Unplugged between pump and read: let the next scan clean it up.
            self._rescan_requested = True
            return None

    def _rescan(self, count: int) -> None:
        present: dict[int, pygame.joystick.JoystickType] = {}
        indices: dict[int, int] = {}
        for index in range(count):
            try:
                # pygame returns the existing object for an already-open device.
                joystick = pygame.joystick.Joystick(index)
                present[joystick.get_instance_id()] = joystick
                indices[joystick.get_instance_id()] = index
            except pygame.error as exc:
                log.debug("Could not open joystick %d: %s", index, exc)
        for instance_id in list(self._joysticks):
            if instance_id not in present:
                self._remove(instance_id)
        self._ignored &= present.keys()
        for instance_id in sorted(present):
            if instance_id in self._joysticks or instance_id in self._ignored:
                continue
            joystick = present[instance_id]
            num_axes, num_buttons = joystick.get_numaxes(), joystick.get_numbuttons()
            if num_axes == 0 and num_buttons == 0:
                self._ignored.add(instance_id)
                log.info("Ignoring '%s': it reports no axes and no buttons", joystick.get_name())
                continue
            if len(self._joysticks) >= MAX_DEVICES:
                debug_throttled("max-devices", 10.0, "More than %d controllers; '%s' is not used",
                                MAX_DEVICES, joystick.get_name())
                continue
            taken = {info.player for info in self._infos.values()}
            player = min(p for p in range(1, MAX_DEVICES + 1) if p not in taken)
            info = DeviceInfo(instance_id, player, joystick.get_name(), joystick.get_guid(),
                              num_axes, num_buttons, joystick.get_numhats(),
                              _sdl_mapping(indices[instance_id]))
            self._joysticks[instance_id] = joystick
            self._infos[instance_id] = info
            log.info("Controller connected: P%d '%s' (%s), SDL mapping: %s", player, info.name,
                     info.guid, dict(info.sdl_mapping) or "none")
            self._on_added(info)
        self._known_count = count

    def _remove(self, instance_id: int) -> None:
        joystick = self._joysticks.pop(instance_id, None)
        info = self._infos.pop(instance_id, None)
        if joystick is not None:
            with contextlib.suppress(pygame.error):
                joystick.quit()
        if info is not None:
            log.info("Controller disconnected: P%d '%s'", info.player, info.name)
            self._on_removed(info)
