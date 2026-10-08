"""The mapping engine: a background thread that polls controllers and injects input.

The UI talks to the engine only through the thread-safe methods at the top of
``MappingEngine`` and reads results from ``snapshot()``. Everything below
``_run`` executes on the engine thread, which owns pygame and the injector.
The loop never creates windows or touches focus, so mapping keeps working
while the app is minimised, unfocused or covered.
"""

from __future__ import annotations

import copy
import ctypes
import heapq
import queue
import sys
import threading
import time
from collections import Counter, deque
from collections.abc import Callable

from app import layouts, model, processing
from app.injector import Injector
from app.logging_setup import debug_throttled, log
from app.processing import StickProcessor, TriggerProcessor

TAP_DURATION_S = 0.03       # taps stay down long enough for frame-polling games
MAX_DT_S = 0.05             # cap mouse integration after a stall
SNAPSHOT_INTERVAL_S = 1 / 60
CALIBRATION_S = 2.0
MAX_STICK_REST = 0.35       # larger resting offsets mean the stick was touched
MAX_TRIGGER_REST = 0.2      # a trigger resting above this was being pressed

BUTTON_SLOTS = {b: f"button:{b}" for b in model.BUTTONS}
DPAD_SLOTS = {d: f"dpad:{d}" for d in model.DIRECTIONS}
STICK_SLOTS = {s: {z: f"stick:{s}:{z}" for z in model.STICK_ZONES} for s in model.STICKS}
TRIGGER_SLOTS = {t: {z: f"trigger:{t}:{z}" for z in model.TRIGGER_ZONES} for t in model.TRIGGERS}


class SlotState:
    """Runtime state of one slot on one device (press/hold/tap state machine)."""

    __slots__ = ("active", "since", "pending", "held", "move_since", "strength", "slot",
                 "suppress_tap")

    def __init__(self) -> None:
        self.active = False
        self.since = 0.0
        self.pending = False      # waiting for the hold threshold
        self.held: dict | None = None  # press action currently held down
        self.move_since = 0.0
        self.strength = 1.0
        self.slot: dict | None = None  # base or layer slot latched when the control activated
        self.suppress_tap = False  # a layer modifier that was used: no short tap on release


class MacroRun:
    """One running macro. Its keys belong to (instance_id, "macro:<n>")."""

    __slots__ = ("source", "owner", "steps", "loop", "index", "wake")

    def __init__(self, source: tuple, owner: tuple, steps: list, loop: bool, now: float) -> None:
        self.source = source      # (instance_id, slot_id, "press" | "tap" | "release")
        self.owner = owner
        self.steps = steps
        self.loop = loop          # repeat until the control is released
        self.index = 0
        self.wake = now


class DeviceRuntime:
    def __init__(self, info, layout: dict, offsets: dict[int, float]) -> None:
        self.info = info
        self.layout = layout
        self.offsets = offsets
        self.buttons = [0] * info.num_buttons
        self.hats = [(0, 0)] * info.num_hats
        self.axes: tuple = (0.0,) * info.num_axes
        self.initialized = False
        self.slots = {slot_id: SlotState() for slot_id in model.all_slot_ids()}
        self.moving: dict[str, SlotState] = {}
        self.sticks = {s: StickProcessor() for s in model.STICKS}
        self.triggers = {t: TriggerProcessor() for t in model.TRIGGERS}
        self.edge_since: dict[str, float | None] = dict.fromkeys(model.STICKS)
        self.results: dict = {}
        self.layer: tuple | None = None  # active entry of MappingEngine._layers, None = base
        self.calibration: dict | None = None

    @property
    def bindings(self) -> dict:
        return self.layout["bindings"]

    def reset_slots(self) -> None:
        for state in self.slots.values():
            state.__init__()
        self.moving.clear()
        for processor in (*self.sticks.values(), *self.triggers.values()):
            processor.reset()
        self.edge_since = dict.fromkeys(model.STICKS)
        self.layer = None


def _offsets_for(profile: dict, guid: str) -> dict[int, float]:
    entry = profile.get("calibration", {}).get(guid)
    return {int(k): float(v) for k, v in entry["axes"].items()} if entry else {}


def _set_timer_resolution(enable: bool) -> None:
    """1 ms Windows timer resolution so the poll loop can hit its period."""
    if sys.platform != "win32":
        return
    try:
        winmm = ctypes.WinDLL("winmm")
        (winmm.timeBeginPeriod if enable else winmm.timeEndPeriod)(1)
    except (OSError, AttributeError):
        pass


def _default_device_manager(on_added, on_removed):
    from app.gamepad import DeviceManager

    return DeviceManager(on_added, on_removed)


class MappingEngine:
    def __init__(self, injector_factory: Callable[[], Injector] = Injector,
                 device_manager_factory: Callable = _default_device_manager) -> None:
        self._injector_factory = injector_factory
        self._device_manager_factory = device_manager_factory
        self._lock = threading.Lock()
        self._commands: queue.SimpleQueue = queue.SimpleQueue()
        self._pending_profile: dict | None = None
        self._superseded = 0
        self._pause_reasons: Counter = Counter()
        self._hz = 250
        self._sensitivity = 1.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: dict = {"paused": False, "user_paused": False, "devices": [],
                                "devices_version": 0, "preview": {}, "stats": {},
                                "held": [], "macros": 0, "error": None}
        self.on_calibrated: Callable[[dict], None] | None = None
        # Engine-thread state.
        self._injector: Injector | None = None
        self._dm = None
        self._profile = model.new_profile("Empty")
        self._slot_map = {sid: model.get_slot(self._profile, sid) for sid in model.all_slot_ids()}
        self._layers: list[tuple] = []
        self._layout_overrides: dict = {}
        self._devices: dict[int, DeviceRuntime] = {}
        self._devices_version = 0
        self._taps: list = []
        self._tap_seq = 0
        self._macros: list[MacroRun] = []
        self._macro_seq = 0
        self._mouse_remainder = [0.0, 0.0]
        self._paused_applied = False
        self._next_snapshot = 0.0
        self._stats: deque = deque(maxlen=250)
        self._error: str | None = None

    # --- thread-safe API (UI thread) -----------------------------------------

    def start(self) -> None:
        if self._thread is None:
            # Hand the GIL over within 1 ms (default 5 ms) so UI redraws cannot
            # push the poll loop past its latency target.
            sys.setswitchinterval(min(sys.getswitchinterval(), 0.001))
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="mapping-engine", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Stop the loop; the thread releases every held key and quits pygame."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def set_profile(self, profile: dict) -> None:
        copied = copy.deepcopy(profile)
        with self._lock:
            if self._pending_profile is not None:
                self._superseded += 1
            self._pending_profile = copied

    def set_layouts(self, overrides: dict) -> None:
        self._commands.put(("layouts", copy.deepcopy(overrides)))

    def set_polling_rate(self, hz: int) -> None:
        self._hz = max(30, int(hz))

    def set_mouse_sensitivity(self, multiplier: float) -> None:
        self._sensitivity = float(multiplier)

    def set_user_paused(self, paused: bool) -> None:
        with self._lock:
            if paused:
                self._pause_reasons["user"] = 1
            else:
                self._pause_reasons.pop("user", None)

    def pause(self, reason: str) -> None:
        """Counted pause, e.g. while a keyboard-capturing modal dialog is open."""
        with self._lock:
            self._pause_reasons[reason] += 1

    def resume(self, reason: str) -> None:
        with self._lock:
            if self._pause_reasons[reason] > 1:
                self._pause_reasons[reason] -= 1
            else:
                self._pause_reasons.pop(reason, None)

    def is_paused(self) -> bool:
        with self._lock:
            return bool(self._pause_reasons)

    def request_calibration(self, instance_id: int) -> None:
        self._commands.put(("calibrate", instance_id))

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot

    # --- engine thread ---------------------------------------------------------

    def _run(self) -> None:
        _set_timer_resolution(True)
        try:
            self._injector = self._injector_factory()
            self._dm = self._device_manager_factory(self._on_device_added, self._on_device_removed)
            self._dm.start()
            last = next_tick = time.perf_counter()
            while not self._stop.is_set():
                start = time.perf_counter()
                interval, last = start - last, start
                try:
                    self._tick(start, min(interval, MAX_DT_S))
                except Exception:
                    log.exception("Error in mapping loop")
                    time.sleep(0.05)
                self._stats.append((time.perf_counter() - start, interval))
                next_tick += 1.0 / self._hz
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.perf_counter()  # fell behind: do not burst to catch up
        except Exception as exc:
            log.exception("Mapping engine stopped")
            self._error = f"Mapping engine stopped: {exc}"
            self._publish(time.perf_counter(), True)
        finally:
            if self._injector is not None:
                self._injector.release_all()
                self._taps.clear()
                self._macros.clear()
            if self._dm is not None:
                try:
                    self._dm.stop()
                except Exception:
                    log.exception("Error while shutting down pygame")
            _set_timer_resolution(False)

    def _tick(self, now: float, dt: float) -> None:
        self._drain_commands(now)
        self._apply_pending_profile()
        paused = self.is_paused()
        if paused != self._paused_applied:
            if paused:
                self._release_everything("injection paused")
            log.debug("Injection %s", "paused" if paused else "resumed")
            self._paused_applied = paused
        events_by_device: dict[int, list] = {}
        for event in self._dm.poll(now):
            events_by_device.setdefault(event.instance_id, []).append(event)
        vx = vy = 0.0
        for dev in list(self._devices.values()):
            dvx, dvy = self._process_device(dev, events_by_device.get(dev.info.instance_id, ()),
                                            now, paused)
            vx += dvx
            vy += dvy
        self._advance_macros(now)
        self._release_due_taps(now)
        self._move_mouse(vx, vy, dt)
        if now >= self._next_snapshot:
            self._next_snapshot = now + SNAPSHOT_INTERVAL_S
            self._publish(now, paused)

    def _drain_commands(self, now: float) -> None:
        while True:
            try:
                command, arg = self._commands.get_nowait()
            except queue.Empty:
                return
            if command == "layouts":
                self._release_everything("layout change")
                self._layout_overrides = arg
                for dev in self._devices.values():
                    info = dev.info
                    dev.layout = layouts.resolve(info.guid, info.num_axes, info.num_buttons,
                                                 info.num_hats, arg, info.sdl_mapping)
                self._devices_version += 1
            elif command == "calibrate":
                dev = self._devices.get(arg)
                if dev is None:
                    self._emit_calibration({"ok": False, "error": "Controller is not connected."})
                else:
                    dev.calibration = {"start": now, "until": now + CALIBRATION_S,
                                       "sums": [0.0] * dev.info.num_axes, "count": 0}

    def _apply_pending_profile(self) -> None:
        with self._lock:
            profile, self._pending_profile = self._pending_profile, None
            superseded, self._superseded = self._superseded, 0
        if profile is None:
            return
        # Edge case: rapid profile switches. set_profile() keeps only the latest
        # request, so a burst of switches collapses into one swap per tick, and
        # every swap first releases all synthetic keys of the old map so nothing
        # held under the previous profile leaks into the new one.
        self._release_everything("profile change")
        if superseded:
            log.debug("Coalesced %d superseded profile switch(es)", superseded)
        self._profile = profile
        self._slot_map = {sid: model.get_slot(profile, sid) for sid in model.all_slot_ids()}
        # (profile index, modifiers, the modifiers' own slots, overrides); a layer that needs
        # more modifiers wins over one that needs fewer (RT+LT beats RT), then list order.
        self._layers = sorted(
            ((i, tuple(layer["modifiers"]), frozenset(model.layer_modifier_slots(layer)),
              layer["slots"]) for i, layer in enumerate(profile["layers"])),
            key=lambda entry: (-len(entry[1]), entry[0]))
        for dev in self._devices.values():
            dev.offsets = _offsets_for(profile, dev.info.guid)
        log.debug("Profile '%s' applied", profile["name"])

    def _release_everything(self, reason: str) -> None:
        released = self._injector.release_all() if self._injector else []
        self._taps.clear()
        self._macros.clear()
        for dev in self._devices.values():
            dev.reset_slots()
        self._mouse_remainder = [0.0, 0.0]
        if released:
            log.debug("Released %s (%s)", released, reason)

    # --- per-device processing -------------------------------------------------

    def _process_device(self, dev: DeviceRuntime, events, now: float,
                        paused: bool) -> tuple[float, float]:
        raw = self._dm.read(dev.info.instance_id)
        if raw is None:
            return 0.0, 0.0
        if not dev.initialized:
            dev.buttons, dev.hats, dev.initialized = list(raw.buttons), list(raw.hats), True
        # Buttons and hats are replayed in arrival order, so a press and release
        # that both land between two polls still yield a full press/release.
        for event in events:
            if event.kind == "button" and event.index < len(dev.buttons):
                dev.buttons[event.index] = event.value
            elif event.kind == "hat" and event.index < len(dev.hats):
                dev.hats[event.index] = event.value
            if not paused:
                self._update_digital(dev, now)
        # Resync with the polled state in case the event queue dropped something.
        if tuple(dev.buttons) != raw.buttons or tuple(dev.hats) != raw.hats:
            dev.buttons, dev.hats = list(raw.buttons), list(raw.hats)
        dev.axes = raw.axes
        if dev.calibration is not None:
            self._sample_calibration(dev, raw.axes, now)
        # Sticks and triggers are processed before any slot is driven, so a trigger used
        # as a layer modifier switches the layer in the same tick it crosses activation.
        self._process_analog(dev, now)
        if paused:
            return 0.0, 0.0
        self._update_digital(dev, now)
        return self._drive_analog(dev, now)

    def _active_layer(self, dev: DeviceRuntime, axes: tuple, buttons: tuple,
                      hats: tuple) -> tuple | None:
        for entry in self._layers:
            if all(self._modifier_held(dev, m, axes, buttons, hats) for m in entry[1]):
                return entry
        return None

    @staticmethod
    def _modifier_held(dev: DeviceRuntime, modifier: str, axes: tuple, buttons: tuple,
                       hats: tuple) -> bool:
        kind, _, name = modifier.partition(":")
        if kind == "button":
            return layouts.read_digital(dev.bindings.get(name), axes, buttons, hats)
        result = dev.results.get(name)  # trigger: held once past its activation point
        return result is not None and "soft" in result.zones

    def _update_digital(self, dev: DeviceRuntime, now: float) -> None:
        b, axes, buttons, hats = dev.bindings, dev.axes, tuple(dev.buttons), tuple(dev.hats)
        layer = self._active_layer(dev, axes, buttons, hats)
        if layer is not dev.layer:
            debug_throttled(f"layer:{dev.info.instance_id}", 0.2, "P%d layer: %s", dev.info.player,
                            "base" if layer is None else self._profile["layers"][layer[0]]["name"])
            dev.layer = layer
        for name, slot_id in BUTTON_SLOTS.items():
            self._drive(dev, slot_id, layouts.read_digital(b.get(name), axes, buttons, hats), 1.0, now)
        up, down, left, right = (layouts.read_digital(b.get(c), axes, buttons, hats)
                                 for c in layouts.DPAD_CONTROLS)
        zones = processing.dpad_zones(up, down, left, right, self._profile["dpad"]["diagonal_mode"])
        for direction, slot_id in DPAD_SLOTS.items():
            self._drive(dev, slot_id, direction in zones, 1.0, now)

    def _process_analog(self, dev: DeviceRuntime, now: float) -> None:
        """Stick and trigger results (zones, strength) for this tick; drives nothing."""
        profile, b, axes = self._profile, dev.bindings, dev.axes
        drift_threshold = profile["anti_drift"]["threshold"]
        drift_delay = profile["anti_drift"]["delay_ms"] / 1000.0
        for stick in model.STICKS:
            bx, by = b.get(f"{stick}_x"), b.get(f"{stick}_y")
            dev.results[stick] = dev.sticks[stick].update(
                layouts.read_axis(bx, axes), layouts.read_axis(by, axes),
                layouts.axis_rest(bx, dev.offsets), layouts.axis_rest(by, dev.offsets),
                profile["sticks"][stick], drift_threshold, drift_delay, now)
        buttons, hats = tuple(dev.buttons), tuple(dev.hats)
        for trigger in model.TRIGGERS:
            value, rest = layouts.read_trigger(b.get(trigger), axes, buttons, hats, dev.offsets)
            dev.results[trigger] = dev.triggers[trigger].update(
                value, rest, profile["triggers"][trigger], drift_threshold, drift_delay, now)

    def _drive_analog(self, dev: DeviceRuntime, now: float) -> tuple[float, float]:
        """Drive stick and trigger slots; returns this device's mouse velocity."""
        profile = self._profile
        vx = vy = 0.0
        for stick in model.STICKS:
            cfg = profile["sticks"][stick]
            result = dev.results[stick]
            for zone, slot_id in STICK_SLOTS[stick].items():
                self._drive(dev, slot_id, zone in result.zones, result.strength, now)
            if len(result.zones) > 1:
                debug_throttled(f"zones:{dev.info.instance_id}:{stick}", 1.0,
                                "P%d %s stick: zones %s active together",
                                dev.info.player, stick, sorted(result.zones))
            if cfg["mode"] == "mouse" and result.active:
                if result.outer and dev.edge_since[stick] is None:
                    dev.edge_since[stick] = now
                elif not result.outer:
                    dev.edge_since[stick] = None
                edge = dev.edge_since[stick]
                mouse = cfg["mouse"]
                speed = (mouse["speed"] * self._sensitivity * result.strength ** mouse["curve"]
                         * processing.accel_multiplier(mouse["accel"], now - edge if edge else 0.0))
                vx += result.unit[0] * speed
                vy += result.unit[1] * speed
            else:
                dev.edge_since[stick] = None

        for trigger in model.TRIGGERS:
            result = dev.results[trigger]
            if result.in_hysteresis:
                debug_throttled(f"jitter:{dev.info.instance_id}:{trigger}", 1.0,
                                "P%d %s at %.3f: held by hysteresis (jitter suppressed)",
                                dev.info.player, trigger, result.value)
            slots = TRIGGER_SLOTS[trigger]
            self._drive(dev, slots["soft"], "soft" in result.zones, result.processed, now)
            self._drive(dev, slots["full"], "full" in result.zones, 1.0, now)

        for state in dev.moving.values():
            action = state.held
            ux, uy = model.DIRECTION_VECTORS[action["direction"]]
            speed = (action["speed"] * self._sensitivity * state.strength
                     * processing.accel_multiplier(action["accel"], now - state.move_since))
            vx += ux * speed
            vy += uy * speed
        return vx, vy

    # --- slot state machine ----------------------------------------------------

    def _drive(self, dev: DeviceRuntime, slot_id: str, active: bool, strength: float,
               now: float) -> None:
        state = dev.slots[slot_id]
        state.strength = strength
        if active == state.active:
            if active and state.pending:
                slot = state.slot
                if (now - state.since) * 1000.0 >= slot["hold_ms"]:
                    state.pending = False
                    self._start(dev, slot_id, state, slot["press"], now)
            return
        if active:
            # Edge case: modifier layers. The slot (base or layer override) is latched when
            # the control activates, so pressing or releasing a modifier while this control
            # is held never swaps its action mid-press: the release ends what the press began.
            slot, layer = self._slot_map[slot_id], dev.layer
            if layer is not None and slot_id not in layer[2] and slot_id in layer[3]:
                slot = layer[3][slot_id]
                for modifier_slot in layer[2]:  # the modifier was used: drop its short tap
                    dev.slots[modifier_slot].suppress_tap = True
            state.slot, state.suppress_tap = slot, False
            state.active, state.since = True, now
            if slot["hold_ms"] > 0:
                state.pending = True
            else:
                self._start(dev, slot_id, state, slot["press"], now)
            return
        slot = state.slot if state.slot is not None else self._slot_map[slot_id]
        state.active, state.slot = False, None
        if state.pending:  # released before the hold threshold: a short tap
            state.pending = False
            if state.suppress_tap:
                log.debug("%s was used as a layer modifier; short tap skipped", slot_id)
            else:
                self._fire(dev, slot_id, "tap", slot["tap"], now)
        else:
            self._stop_held(dev, slot_id, state)
        self._fire(dev, slot_id, "release", slot["release"], now)

    def _start(self, dev: DeviceRuntime, slot_id: str, state: SlotState, action: dict,
               now: float) -> None:
        kind = action["type"]
        if kind == "none":
            return
        if kind == "macro":
            if self._start_macro(dev, slot_id, "press", action, now) and action["loop"]:
                state.held = action  # repeats until the control is released
            return
        if kind in ("key", "mouse_button") and action["mode"] == "tap":
            self._tap(action, now)
            return
        owner = (dev.info.instance_id, slot_id)
        if kind == "key":
            self._injector.press_keys(owner, action["keys"])
        elif kind == "mouse_button":
            self._injector.press_button(owner, action["button"])
        else:
            state.move_since = now
            dev.moving[slot_id] = state
        state.held = action

    def _stop_held(self, dev: DeviceRuntime, slot_id: str, state: SlotState) -> None:
        action, state.held = state.held, None
        if action is None:
            return
        owner = (dev.info.instance_id, slot_id)
        if action["type"] == "key":
            self._injector.release_keys(owner, action["keys"])
        elif action["type"] == "mouse_button":
            self._injector.release_button(owner, action["button"])
        elif action["type"] == "macro":
            source = (dev.info.instance_id, slot_id, "press")
            for run in [r for r in self._macros if r.source == source and r.loop]:
                self._end_macro(run)
        else:
            dev.moving.pop(slot_id, None)

    def _fire(self, dev: DeviceRuntime, slot_id: str, phase: str, action: dict,
              now: float) -> None:
        """One-shot action of a tap or release slot."""
        if action["type"] == "macro":
            self._start_macro(dev, slot_id, phase, action, now)
        else:
            self._tap(action, now)

    def _tap(self, action: dict, now: float) -> None:
        kind = action["type"]
        if kind not in ("key", "mouse_button"):
            return
        self._tap_seq += 1
        owner = ("tap", self._tap_seq)
        if kind == "key":
            self._injector.press_keys(owner, action["keys"], retrigger=True)
        else:
            self._injector.press_button(owner, action["button"], retrigger=True)
        heapq.heappush(self._taps, (now + TAP_DURATION_S, self._tap_seq, owner, action))

    def _release_due_taps(self, now: float) -> None:
        while self._taps and self._taps[0][0] <= now:
            _, _, owner, action = heapq.heappop(self._taps)
            if action["type"] == "key":
                self._injector.release_keys(owner, action["keys"])
            else:
                self._injector.release_button(owner, action["button"])

    # --- macros ------------------------------------------------------------------

    def _start_macro(self, dev: DeviceRuntime, slot_id: str, phase: str, action: dict,
                     now: float) -> bool:
        source = (dev.info.instance_id, slot_id, phase)
        if any(run.source == source for run in self._macros):
            # Edge case: a macro never overlaps itself. Triggering it again while it is
            # still running is ignored instead of interleaving two copies of its keys.
            debug_throttled(f"macro-busy:{slot_id}", 1.0, "Macro on %s still running; trigger "
                            "ignored", slot_id)
            return False
        self._macro_seq += 1
        run = MacroRun(source, (dev.info.instance_id, f"macro:{self._macro_seq}"),
                       action["steps"], phase == "press" and action["loop"], now)
        self._macros.append(run)
        if not self._step_macro(run, now):  # the first steps go out in this tick
            self._end_macro(run)
        return True

    def _advance_macros(self, now: float) -> None:
        for run in list(self._macros):
            if not self._step_macro(run, now):
                self._end_macro(run)

    def _step_macro(self, run: MacroRun, now: float) -> bool:
        """Run every step that is due; False once a single-shot macro has finished."""
        steps, injector, wrapped = run.steps, self._injector, False
        while run.wake <= now:
            if run.index >= len(steps):
                if not run.loop:
                    return False
                if wrapped:  # at most one restart per tick, even for a macro without waits
                    break
                wrapped, run.index = True, 0
                continue
            step = steps[run.index]
            run.index += 1
            op = step["op"]
            if op == "wait":
                # Waits count from when the previous one was due, so recorded timing does
                # not drift by a tick per step; after a stall, count from now (no burst).
                base = run.wake if now - run.wake < MAX_DT_S else now
                run.wake = base + step["ms"] / 1000.0
            elif op == "key_down":
                injector.press_keys(run.owner, [step["key"]])
            elif op == "key_up":
                injector.release_keys(run.owner, [step["key"]])
            elif op == "button_down":
                injector.press_button(run.owner, step["button"])
            else:
                injector.release_button(run.owner, step["button"])
        return True

    def _end_macro(self, run: MacroRun) -> None:
        self._macros.remove(run)
        released = self._injector.release_owners(lambda owner: owner == run.owner)
        if released:
            log.debug("Macro on %s ended holding %s; released", run.source[1], released)

    def _move_mouse(self, vx: float, vy: float, dt: float) -> None:
        if vx == 0.0 and vy == 0.0:
            self._mouse_remainder = [0.0, 0.0]
            return
        fx = vx * dt + self._mouse_remainder[0]
        fy = vy * dt + self._mouse_remainder[1]
        ix, iy = int(fx), int(fy)
        self._mouse_remainder = [fx - ix, fy - iy]
        self._injector.move_mouse(ix, iy)

    # --- devices and calibration -----------------------------------------------

    def _on_device_added(self, info) -> None:
        layout = layouts.resolve(info.guid, info.num_axes, info.num_buttons, info.num_hats,
                                 self._layout_overrides, info.sdl_mapping)
        self._devices[info.instance_id] = DeviceRuntime(info, layout,
                                                        _offsets_for(self._profile, info.guid))
        self._devices_version += 1

    def _on_device_removed(self, info) -> None:
        self._devices.pop(info.instance_id, None)
        # Edge case: controller unplugged while keys are held. Its release events
        # will never arrive, so every key and mouse button owned by this device
        # (macros included) is released now and its macros stop; short taps finish
        # on their own 30 ms timer.
        self._macros = [run for run in self._macros if run.owner[0] != info.instance_id]
        released = self._injector.release_owners(lambda owner: owner[0] == info.instance_id)
        if released:
            log.debug("'%s' disconnected while holding %s; released", info.name, released)
        self._devices_version += 1

    def _sample_calibration(self, dev: DeviceRuntime, axes: tuple, now: float) -> None:
        cal = dev.calibration
        for i, value in enumerate(axes[:len(cal["sums"])]):
            cal["sums"][i] += value
        cal["count"] += 1
        if now < cal["until"]:
            return
        dev.calibration = None
        roles = layouts.axis_roles(dev.bindings)
        accepted: dict[int, float] = {}
        warnings: list[str] = []
        for i, total in enumerate(cal["sums"]):
            mean = total / max(cal["count"], 1)
            if roles.get(i) == "trigger" and mean > MAX_TRIGGER_REST:
                warnings.append(f"Axis {i} (trigger) was pressed ({mean:+.2f}); kept the old value.")
            elif roles.get(i) != "trigger" and abs(mean) > MAX_STICK_REST:
                warnings.append(f"Axis {i} was not centred ({mean:+.2f}); kept the old value.")
            else:
                accepted[i] = round(mean, 4)
        dev.offsets.update(accepted)
        for processor in dev.sticks.values():
            processor.reset()
        log.debug("Calibrated '%s' from %d samples: %s", dev.info.name, cal["count"], accepted)
        self._emit_calibration({"ok": True, "guid": dev.info.guid, "device": dev.info.name,
                                "axes": accepted, "warnings": warnings})

    def _emit_calibration(self, result: dict) -> None:
        callback = self.on_calibrated
        if callback is not None:
            try:
                callback(result)
            except Exception:
                log.exception("Calibration callback failed")

    # --- snapshot for the UI ---------------------------------------------------

    def _publish(self, now: float, paused: bool) -> None:
        devices, previews = [], {}
        for dev in sorted(self._devices.values(), key=lambda d: d.info.player):
            info, b = dev.info, dev.bindings
            axes, buttons, hats = dev.axes, tuple(dev.buttons), tuple(dev.hats)
            devices.append({"instance_id": info.instance_id, "player": info.player,
                            "name": info.name, "guid": info.guid, "axes": info.num_axes,
                            "buttons": info.num_buttons, "hats": info.num_hats,
                            "preset": dev.layout["preset"], "base": dev.layout["base"],
                            "sdl_mapping": info.sdl_mapping})
            cal = dev.calibration
            previews[info.instance_id] = {
                "raw": {"axes": axes, "buttons": buttons, "hats": hats},
                "pressed": [c for c in model.BUTTONS + layouts.DPAD_CONTROLS
                            if layouts.read_digital(b.get(c), axes, buttons, hats)],
                "results": dict(dev.results),
                "active_slots": [sid for sid, st in dev.slots.items() if st.active],
                "layer": None if dev.layer is None else dev.layer[0],
                "calibrating": None if cal is None else min((now - cal["start"]) / CALIBRATION_S, 1.0),
            }
        stats = {}
        if self._stats:
            work = [w for w, _ in self._stats]
            intervals = [i for _, i in self._stats]
            mean_interval = sum(intervals) / len(intervals)
            stats = {"target_hz": self._hz,
                     "hz": 1.0 / mean_interval if mean_interval > 0 else 0.0,
                     "work_ms": 1000.0 * sum(work) / len(work),
                     "max_interval_ms": 1000.0 * max(intervals)}
        snapshot = {
            "paused": paused,
            "devices": devices,
            "devices_version": self._devices_version,
            "preview": previews,
            "stats": stats,
            "held": self._injector.held() if self._injector else [],
            "macros": len(self._macros),
            "error": self._error,
        }
        with self._lock:
            snapshot["user_paused"] = "user" in self._pause_reasons
            self._snapshot = snapshot
        if stats and stats["max_interval_ms"] > 8.0 + 1000.0 / self._hz:
            debug_throttled("latency", 5.0, "Slow poll: max interval %.1f ms", stats["max_interval_ms"])
