"""Per-control editor panels (button, D-pad, stick, trigger) with live previews."""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from app import model, processing
from app.ui.slot_editor import SlotEditor
from app.ui.widgets import NumberField, ZonePicker, palette, section

DIRECTION_GRID = [["nw", "n", "ne"], ["w", None, "e"], ["sw", "s", "se"]]
STICK_GRID = [["nw", "n", "ne"], ["w", "outer", "e"], ["sw", "s", "se"]]
TRIGGER_GRID = [["soft", "full"]]
ZONE_LABELS = {**model.DIRECTION_ARROWS, "outer": "Outer"}
DIAGONAL_LABELS = {"combined": "Own zone", "cardinals": "Both cardinals"}
STICK_MODE_LABELS = {"zones": "Directional zones", "mouse": "Mouse"}
RESPONSE_LABELS = {"linear": "Linear", "curved": "Curved"}


def _key_for(mapping: dict, label: str) -> str:
    return next(k for k, v in mapping.items() if v == label)


def _segmented(master, label: str, choices: dict, command: Callable[[str], None]) -> ctk.CTkSegmentedButton:
    row = ctk.CTkFrame(master, fg_color="transparent")
    row.pack(fill="x", pady=2)
    ctk.CTkLabel(row, text=label, width=150, anchor="w").pack(side="left")
    widget = ctk.CTkSegmentedButton(row, values=list(choices.values()),
                                    command=lambda value: command(_key_for(choices, value)))
    widget.pack(side="left")
    return widget


class _ZoneEditorBase(ctk.CTkFrame):
    """Shared plumbing: a zone picker on top of one SlotEditor."""

    def __init__(self, master, on_change: Callable[[], None], capture_key) -> None:
        super().__init__(master, fg_color="transparent")
        self._on_change = on_change
        self._capture_key = capture_key
        self._zone = ""

    def _make_slot_editor(self) -> SlotEditor:
        return SlotEditor(self, self._slot_changed, self._capture_key)

    def _slot_changed(self) -> None:
        self._update_picker()  # markers only; never rebuilds the slot editor mid-typing
        self._on_change()

    def _changed(self) -> None:
        self._on_change()

    def _update_picker(self) -> None:
        raise NotImplementedError


class ButtonEditor(ctk.CTkFrame):
    def __init__(self, master, on_change: Callable[[], None], capture_key) -> None:
        super().__init__(master, fg_color="transparent")
        self.slot_editor = SlotEditor(self, on_change, capture_key)
        self.slot_editor.pack(fill="x")

    def load(self, profile: dict, control_id: str, zone: str | None = None) -> None:
        name = control_id.split(":")[1]
        self.slot_editor.load(profile["buttons"][name], model.BUTTON_LABELS[name])

    def update_live(self, preview: dict | None) -> None:
        pass


class DpadEditor(_ZoneEditorBase):
    def __init__(self, master, on_change, capture_key) -> None:
        super().__init__(master, on_change, capture_key)
        self._dpad: dict = model.new_profile("")["dpad"]  # placeholder until load()
        self._zone = "n"
        section(self, "D-pad").pack(fill="x")
        self._diagonal = _segmented(self, "Diagonals", DIAGONAL_LABELS, self._set_diagonal)
        ctk.CTkLabel(self, text="Own zone: a diagonal fires its own mapping. Both cardinals: "
                                "it fires the two neighbouring directions together.",
                     text_color="gray", anchor="w", justify="left", wraplength=420).pack(fill="x")
        self._picker = ZonePicker(self, DIRECTION_GRID, ZONE_LABELS, self._select)
        self._picker.pack(pady=8)
        self.slot_editor = self._make_slot_editor()
        self.slot_editor.pack(fill="x")

    def load(self, profile: dict, control_id: str, zone: str | None = None) -> None:
        self._dpad = profile["dpad"]
        self._diagonal.set(DIAGONAL_LABELS[self._dpad["diagonal_mode"]])
        self._select(zone or self._zone)

    def _enabled(self) -> set[str]:
        if self._dpad["diagonal_mode"] == "cardinals":
            return {"n", "e", "s", "w"}
        return set(model.DIRECTIONS)

    def _select(self, zone: str) -> None:
        self._zone = zone if zone in self._enabled() else "n"
        self._update_picker()
        self.slot_editor.load(self._dpad["zones"][self._zone],
                              f"D-pad {model.DIRECTION_LABELS[self._zone].lower()}")

    def _update_picker(self) -> None:
        mapped = {d for d, slot in self._dpad["zones"].items() if model.slot_is_mapped(slot)}
        self._picker.update_state(self._zone, mapped, self._enabled())

    def _set_diagonal(self, mode: str) -> None:
        self._dpad["diagonal_mode"] = mode
        self._select(self._zone)
        self._changed()

    def update_live(self, preview: dict | None) -> None:
        pass


class StickPreview(tk.Canvas):
    SIZE = 200
    WIDTH = 300

    def __init__(self, master) -> None:
        super().__init__(master, width=self.WIDTH, height=self.SIZE + 34, highlightthickness=0)

    def render(self, cfg: dict, result) -> None:
        p = palette()
        self.configure(bg=p["panel"])
        self.delete("all")
        c = self.SIZE / 2
        radius = c - 8
        dx = (self.WIDTH - self.SIZE) / 2  # horizontal offset of the circle
        dz, outer = cfg["deadzone"] * radius, cfg["outer"] * radius
        zones_mode = cfg["mode"] == "zones"
        count = cfg["zone_count"]
        width = 360.0 / count
        if result is not None and result.active and zones_mode and result.sector:
            sectors = processing.SECTORS_8 if count == 8 else processing.SECTORS_4
            centre = sectors.index(result.sector) * width
            self.create_arc(c - radius, c - radius, c + radius, c + radius,
                            start=90 - centre - width / 2, extent=width,
                            fill=p["zone"], outline="", stipple="gray50")
        self.create_oval(c - radius, c - radius, c + radius, c + radius, outline=p["outline"], width=2)
        self.create_oval(c - outer, c - outer, c + outer, c + outer, outline=p["mapped"], dash=(4, 3))
        self.create_oval(c - dz, c - dz, c + dz, c + dz, outline=p["outline"], fill=p["body"])
        if zones_mode:
            for k in range(count):
                angle = math.radians(k * width + width / 2)
                sx, sy = math.sin(angle), -math.cos(angle)
                self.create_line(c + sx * dz, c + sy * dz, c + sx * radius, c + sy * radius,
                                 fill=p["grid"])
        caption = "no controller"
        if result is not None:
            rx, ry = result.raw
            px, py = result.processed
            self._dot(c + rx * radius, c + ry * radius, 5, p["raw"])
            self._dot(c + px * radius, c + py * radius, 6, p["processed"])
            zones = ", ".join(sorted(result.zones)) or "-"
            caption = f"raw {rx:+.2f} {ry:+.2f}   out {px:+.2f} {py:+.2f}\nzones: {zones}"
        self.move("all", dx, 0)
        self.create_text(self.WIDTH / 2, self.SIZE + 16, text=caption, fill=p["text"],
                         font=("Segoe UI", 9))

    def _dot(self, x: float, y: float, r: float, color: str) -> None:
        self.create_oval(x - r, y - r, x + r, y + r, fill=color, outline="")


class StickEditor(_ZoneEditorBase):
    def __init__(self, master, on_change, capture_key) -> None:
        super().__init__(master, on_change, capture_key)
        self._stick = "left"
        self._cfg: dict = model.new_profile("")["sticks"]["left"]  # placeholder until load()
        self._zone = "n"
        self._title = section(self, "")
        self._title.pack(fill="x")
        self._mode = _segmented(self, "Mode", STICK_MODE_LABELS, self._set_mode)
        self._fields = [
            NumberField(self, "Deadzone (circular)", lambda: self._cfg["deadzone"],
                        self._set_deadzone, 0.0, 0.9, percent=True),
            NumberField(self, "Outer threshold", lambda: self._cfg["outer"],
                        self._set_outer, 0.05, 1.0, percent=True),
        ]
        for field in self._fields:
            field.pack(fill="x", pady=2)
        self._zone_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._count = _segmented(self._zone_frame, "Zones", {8: "8-way", 4: "4-way"}, self._set_count)
        self._diagonal = _segmented(self._zone_frame, "Diagonals", DIAGONAL_LABELS, self._set_diagonal)
        self._mouse_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._mouse_fields = [
            NumberField(self._mouse_frame, "Mouse speed", self._mouse_getter("speed"),
                        self._mouse_setter("speed"), 50, 5000, unit="px/s"),
            NumberField(self._mouse_frame, "Response curve", self._mouse_getter("curve"),
                        self._mouse_setter("curve"), 1.0, 3.0, decimals=2),
            NumberField(self._mouse_frame, "Acceleration", self._mouse_getter("accel"),
                        self._mouse_setter("accel"), 0.0, 5.0, decimals=1, unit="x/s"),
        ]
        for field in self._mouse_fields:
            field.pack(fill="x", pady=2)
        self._hint = ctk.CTkLabel(self, text="", text_color="gray", anchor="w", justify="left",
                                  wraplength=420)
        self._preview = StickPreview(self)
        self._picker = ZonePicker(self, STICK_GRID, ZONE_LABELS, self._select)
        self.slot_editor = self._make_slot_editor()

    def load(self, profile: dict, control_id: str, zone: str | None = None) -> None:
        stick = control_id.split(":")[1]
        if stick != self._stick:
            self._zone = "n"
        self._stick = stick
        self._cfg = profile["sticks"][stick]
        self._title.configure(text=model.STICK_LABELS[self._stick])
        self._mode.set(STICK_MODE_LABELS[self._cfg["mode"]])
        self._count.set({8: "8-way", 4: "4-way"}[self._cfg["zone_count"]])
        self._diagonal.set(DIAGONAL_LABELS[self._cfg["diagonal_mode"]])
        for field in self._fields + self._mouse_fields:
            field.refresh()
        self._layout()
        self._select(self._zone)

    def _layout(self) -> None:
        for widget in (self._zone_frame, self._mouse_frame, self._hint, self._preview,
                       self._picker, self.slot_editor):
            widget.pack_forget()
        if self._cfg["mode"] == "zones":
            self._zone_frame.pack(fill="x")
            self._hint.configure(text="Zones activate outside the deadzone. The outer ring fires "
                                      "when the stick passes the outer threshold.")
        else:
            self._mouse_frame.pack(fill="x")
            self._hint.configure(text="Mouse speed is reached at the outer threshold. Curve > 1 "
                                      "gives finer control near the centre; acceleration ramps "
                                      "speed up while the stick is held at the outer ring.")
        self._hint.pack(fill="x", pady=(2, 4))
        self._preview.pack(pady=4)
        self._picker.pack(pady=6)
        self.slot_editor.pack(fill="x")

    def _enabled(self) -> set[str]:
        if self._cfg["mode"] == "mouse":
            return {"outer"}
        if self._cfg["zone_count"] == 4 or self._cfg["diagonal_mode"] == "cardinals":
            return {"n", "e", "s", "w", "outer"}
        return set(model.STICK_ZONES)

    def _select(self, zone: str) -> None:
        enabled = self._enabled()
        self._zone = zone if zone in enabled else ("n" if "n" in enabled else "outer")
        self._update_picker()
        self.slot_editor.load(self._cfg["zones"][self._zone],
                              model.slot_title(f"stick:{self._stick}:{self._zone}"))

    def _update_picker(self) -> None:
        mapped = {z for z, slot in self._cfg["zones"].items() if model.slot_is_mapped(slot)}
        self._picker.update_state(self._zone, mapped, self._enabled())

    def _set_mode(self, mode: str) -> None:
        self._cfg["mode"] = mode
        self._layout()
        self._select(self._zone)
        self._changed()

    def _set_count(self, count: int) -> None:
        self._cfg["zone_count"] = count
        self._select(self._zone)
        self._changed()

    def _set_diagonal(self, mode: str) -> None:
        self._cfg["diagonal_mode"] = mode
        self._select(self._zone)
        self._changed()

    def _set_deadzone(self, value: float) -> None:
        self._cfg["deadzone"] = value
        self._cfg["outer"] = max(self._cfg["outer"], min(value + 0.05, 1.0))
        self._fields[1].refresh()
        self._changed()

    def _set_outer(self, value: float) -> None:
        self._cfg["outer"] = max(value, min(self._cfg["deadzone"] + 0.05, 1.0))
        self._changed()

    def _mouse_getter(self, key: str) -> Callable[[], float]:
        return lambda: self._cfg["mouse"][key]

    def _mouse_setter(self, key: str) -> Callable[[float], None]:
        def apply(value: float) -> None:
            self._cfg["mouse"][key] = value
            self._changed()
        return apply

    def update_live(self, preview: dict | None) -> None:
        result = preview["results"].get(self._stick) if preview else None
        self._preview.render(self._cfg, result)


class TriggerPreview(tk.Canvas):
    WIDTH, HEIGHT = 380, 96

    def __init__(self, master) -> None:
        super().__init__(master, width=self.WIDTH, height=self.HEIGHT, highlightthickness=0)

    def render(self, cfg: dict, result) -> None:
        p = palette()
        self.configure(bg=p["panel"])
        self.delete("all")
        x0, bar_w = 62, 200
        raw = result.raw if result is not None else 0.0
        out = result.processed if result is not None else 0.0
        for y, label, value, color in ((18, "Raw", raw, p["raw"]), (52, "Output", out, p["processed"])):
            self.create_text(x0 - 8, y + 9, text=label, anchor="e", fill=p["text"], font=("Segoe UI", 9))
            self.create_rectangle(x0, y, x0 + bar_w, y + 18, outline=p["outline"], fill=p["body"])
            if value > 0:
                self.create_rectangle(x0, y, x0 + bar_w * value, y + 18, outline="", fill=color)
        for value, color in ((cfg["activation"], p["mapped"]), (cfg["full"], p["selected"])):
            x = x0 + bar_w * value
            self.create_line(x, 12, x, 40, fill=color, width=2)
        # Response curve between the two breakpoints.
        gx, gy, gw, gh = 290, 10, 80, 66
        self.create_rectangle(gx, gy, gx + gw, gy + gh, outline=p["outline"])
        points = []
        for i in range(41):
            v = i / 40
            o = processing.trigger_response(v, cfg["activation"], cfg["full"], cfg["response"],
                                            cfg["curve_exponent"])
            points += [gx + v * gw, gy + gh - o * gh]
        self.create_line(*points, fill=p["processed"], width=2)
        if result is not None:
            self.create_oval(gx + raw * gw - 3, gy + gh - out * gh - 3, gx + raw * gw + 3,
                             gy + gh - out * gh + 3, fill=p["selected"], outline="")
        zones = ", ".join(model.TRIGGER_ZONE_LABELS[z] for z in sorted(result.zones)) if result else ""
        caption = f"{raw:.0%} -> {out:.0%}   {zones}" if result is not None else "no controller"
        self.create_text(x0, 84, text=caption, anchor="w", fill=p["text"], font=("Segoe UI", 9))


class TriggerEditor(_ZoneEditorBase):
    def __init__(self, master, on_change, capture_key) -> None:
        super().__init__(master, on_change, capture_key)
        self._trigger = "lt"
        self._cfg: dict = model.new_profile("")["triggers"]["lt"]  # placeholder until load()
        self._zone = "soft"
        self._title = section(self, "")
        self._title.pack(fill="x")
        self._fields = [
            NumberField(self, "Activation threshold", lambda: self._cfg["activation"],
                        self._set_activation, 0.02, 0.95, percent=True),
            NumberField(self, "Full-press threshold", lambda: self._cfg["full"],
                        self._set_full, 0.04, 1.0, percent=True),
        ]
        for field in self._fields:
            field.pack(fill="x", pady=2)
        self._response = _segmented(self, "Response", RESPONSE_LABELS, self._set_response)
        self._exponent = NumberField(self, "Curve exponent", lambda: self._cfg["curve_exponent"],
                                     self._set_exponent, 0.3, 4.0, decimals=2)
        self._exponent.pack(fill="x", pady=2)
        ctk.CTkLabel(self, text="Values jittering around a threshold are absorbed by a 4% "
                                "hysteresis band.", text_color="gray", anchor="w").pack(fill="x")
        self._preview = TriggerPreview(self)
        self._preview.pack(pady=4)
        self._picker = ZonePicker(self, TRIGGER_GRID, model.TRIGGER_ZONE_LABELS, self._select,
                                  cell_width=120)
        self._picker.pack(pady=6)
        self.slot_editor = self._make_slot_editor()
        self.slot_editor.pack(fill="x")

    def load(self, profile: dict, control_id: str, zone: str | None = None) -> None:
        self._trigger = control_id.split(":")[1]
        self._cfg = profile["triggers"][self._trigger]
        self._title.configure(text=model.TRIGGER_LABELS[self._trigger])
        self._response.set(RESPONSE_LABELS[self._cfg["response"]])
        for field in self._fields + [self._exponent]:
            field.refresh()
        self._exponent.set_enabled(self._cfg["response"] == "curved")
        self._select(self._zone)

    def _select(self, zone: str) -> None:
        self._zone = zone
        self._update_picker()
        self.slot_editor.load(self._cfg["zones"][zone],
                              model.slot_title(f"trigger:{self._trigger}:{zone}"))

    def _update_picker(self) -> None:
        mapped = {z for z, slot in self._cfg["zones"].items() if model.slot_is_mapped(slot)}
        self._picker.update_state(self._zone, mapped, set(model.TRIGGER_ZONES))

    def _set_activation(self, value: float) -> None:
        self._cfg["activation"] = value
        self._cfg["full"] = max(self._cfg["full"], min(value + 0.02, 1.0))
        self._fields[1].refresh()
        self._changed()

    def _set_full(self, value: float) -> None:
        self._cfg["full"] = max(value, self._cfg["activation"] + 0.02)
        self._changed()

    def _set_response(self, response: str) -> None:
        self._cfg["response"] = response
        self._exponent.set_enabled(response == "curved")
        self._changed()

    def _set_exponent(self, value: float) -> None:
        self._cfg["curve_exponent"] = value
        self._changed()

    def update_live(self, preview: dict | None) -> None:
        result = preview["results"].get(self._trigger) if preview else None
        self._preview.render(self._cfg, result)
