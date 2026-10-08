"""Clickable drawing of a generic controller with live input highlighting."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from app import model
from app.ui.widgets import palette

STICK_CENTRES = {"left": (165, 140), "right": (365, 215)}
STICK_RADIUS, STICK_KNOB = 40, 18
TRIGGER_RECTS = {"lt": (95, 8, 185, 36), "rt": (415, 8, 505, 36)}
BUMPER_RECTS = {"lb": (85, 44, 195, 64), "rb": (405, 44, 515, 64)}
FACE_CENTRES = {"y": (435, 112), "x": (407, 140), "b": (463, 140), "a": (435, 168)}
MENU_OVALS = {"back": (242, 112, 268, 128), "start": (332, 112, 358, 128)}
GUIDE_CENTRE = (300, 104)
DPAD_ARMS = {  # zone -> (rect, raw control used for highlighting)
    "n": ((224, 182, 246, 204), "dpad_up"), "s": ((224, 226, 246, 248), "dpad_down"),
    "w": ((202, 204, 224, 226), "dpad_left"), "e": ((246, 204, 268, 226), "dpad_right"),
}
BODY = (150, 70, 450, 70, 520, 95, 560, 200, 565, 290, 535, 322, 495, 316, 440, 252,
        160, 252, 105, 316, 65, 322, 35, 290, 40, 200, 80, 95)


class ControllerView(tk.Canvas):
    WIDTH, HEIGHT = 600, 350

    def __init__(self, master, on_select: Callable[[str, str | None], None]) -> None:
        super().__init__(master, width=self.WIDTH, height=self.HEIGHT, highlightthickness=0)
        self._on_select = on_select
        self._selected = "button:a"
        self._profile: dict | None = None
        self._shapes: dict[str, list[int]] = {}
        self._labels: dict[str, int] = {}
        self._fills: dict[int, str] = {}
        self._knobs: dict[str, tuple[int, int]] = {}
        self._trigger_fill: dict[str, int] = {}
        self._status = 0
        self.redraw()

    # --- drawing -------------------------------------------------------------

    def redraw(self) -> None:
        p = palette()
        self.delete("all")
        self._shapes.clear()
        self._labels.clear()
        self._fills.clear()
        self.configure(bg=p["panel"])
        self.create_polygon(BODY, smooth=True, fill=p["body"], outline=p["outline"], width=2)
        for trigger, rect in TRIGGER_RECTS.items():
            cid = f"trigger:{trigger}"
            self._shape(cid, self.create_rectangle(rect, fill=p["control"], outline=p["outline"]))
            x0, y0, _x1, y1 = rect
            self._trigger_fill[trigger] = self.create_rectangle(x0, y0, x0, y1, fill=p["pressed"],
                                                                outline="", tags=(f"ctl:{cid}",))
            self._label(cid, (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2, trigger.upper())
        for bumper, rect in BUMPER_RECTS.items():
            cid = f"button:{bumper}"
            self._shape(cid, self.create_rectangle(rect, fill=p["control"], outline=p["outline"]))
            self._label(cid, (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2, bumper.upper())
        for stick, (cx, cy) in STICK_CENTRES.items():
            cid = f"stick:{stick}"
            r = STICK_RADIUS
            self._shape(cid, self.create_oval(cx - r, cy - r, cx + r, cy + r,
                                              fill=p["control"], outline=p["outline"], width=2))
            self._label(cid, cx, cy + r + 10, model.STICK_LABELS[stick])
            click = "button:ls" if stick == "left" else "button:rs"
            k = STICK_KNOB
            knob = self.create_oval(cx - k, cy - k, cx + k, cy + k, fill=p["body"], outline=p["outline"])
            self._shape(click, knob)
            text = self._label(click, cx, cy, "L3" if stick == "left" else "R3")
            self._knobs[stick] = (knob, text)
        for zone, (rect, _raw) in DPAD_ARMS.items():
            item = self.create_rectangle(rect, fill=p["control"], outline=p["outline"])
            self._shape("dpad", item, zone)
        self.create_rectangle(224, 204, 246, 226, fill=p["control"], outline="", tags=("ctl:dpad",))
        self._label("dpad", 235, 262, "D-pad")
        for button, rect in MENU_OVALS.items():
            cid = f"button:{button}"
            self._shape(cid, self.create_oval(rect, fill=p["control"], outline=p["outline"]))
            self._label(cid, (rect[0] + rect[2]) / 2, rect[3] + 10, button.title())
        gx, gy = GUIDE_CENTRE
        self._shape("button:guide", self.create_oval(gx - 14, gy - 14, gx + 14, gy + 14,
                                                     fill=p["control"], outline=p["outline"]))
        self._label("button:guide", gx, gy, "G")
        for button, (cx, cy) in FACE_CENTRES.items():
            cid = f"button:{button}"
            self._shape(cid, self.create_oval(cx - 14, cy - 14, cx + 14, cy + 14,
                                              fill=p["control"], outline=p["outline"], width=2))
            self._label(cid, cx, cy, button.upper())
        self._status = self.create_text(self.WIDTH / 2, self.HEIGHT - 12, text="Click a control to edit it",
                                        fill=p["muted"], font=("Segoe UI", 10))
        for cid in set(self._shapes) | set(self._labels):
            tag = f"ctl:{cid}"
            self.tag_bind(tag, "<Enter>", lambda _e, c=cid: self._hover(c))
            self.tag_bind(tag, "<Leave>", lambda _e: self._hover(None))
            if cid != "dpad":
                self.tag_bind(tag, "<Button-1>", lambda _e, c=cid: self._on_select(c, None))
        self.tag_bind("ctl:dpad", "<Button-1>", self._dpad_click)
        self._apply_static()

    def _shape(self, cid: str, item: int, zone: str | None = None) -> None:
        tags = (f"ctl:{cid}",) + ((f"zone:{zone}",) if zone else ())
        self.itemconfigure(item, tags=tags)
        self._shapes.setdefault(cid, []).append(item)

    def _label(self, cid: str, x: float, y: float, text: str) -> int:
        """Control caption; drawn in the accent colour when the control is mapped."""
        item = self.create_text(x, y, text=text, font=("Segoe UI", 9, "bold"), tags=(f"ctl:{cid}",),
                                fill=palette()["text"])
        self._labels[cid] = item
        return item

    def _dpad_click(self, _event) -> None:
        current = self.find_withtag("current")
        tags = self.gettags(current[0]) if current else ()
        zone = next((t.split(":")[1] for t in tags if t.startswith("zone:")), None)
        self._on_select("dpad", zone)

    # --- state -----------------------------------------------------------------

    def set_profile(self, profile: dict) -> None:
        self._profile = profile
        self._apply_static()

    def select(self, control_id: str) -> None:
        self._selected = control_id
        self._apply_static()

    def _apply_static(self) -> None:
        p = palette()
        for cid, items in self._shapes.items():
            selected = cid == self._selected
            for item in items:
                self.itemconfigure(item, outline=p["selected"] if selected else p["outline"],
                                   width=3 if selected else (2 if cid.startswith("stick") else 1))
        for cid, item in self._labels.items():
            mapped = self._profile is not None and self._mapped(cid)
            self.itemconfigure(item, fill=p["mapped"] if mapped else p["text"])

    def _mapped(self, cid: str) -> bool:
        profile = self._profile
        kind, _, name = cid.partition(":")
        if kind == "button":
            return model.slot_is_mapped(profile["buttons"][name])
        if kind == "dpad":
            return any(model.slot_is_mapped(s) for s in profile["dpad"]["zones"].values())
        if kind == "stick":
            cfg = profile["sticks"][name]
            return cfg["mode"] == "mouse" or any(model.slot_is_mapped(s) for s in cfg["zones"].values())
        return any(model.slot_is_mapped(s) for s in profile["triggers"][name]["zones"].values())

    def _summary(self, cid: str) -> str:
        profile = self._profile
        kind, _, name = cid.partition(":")
        if kind == "button":
            return f"{model.BUTTON_LABELS[name]}: {model.describe_slot(profile['buttons'][name])}"
        if kind == "dpad":
            zones = profile["dpad"]["zones"]
            parts = [f"{model.DIRECTION_ARROWS[d]} {model.describe_slot(zones[d])}"
                     for d in model.DIRECTIONS if model.slot_is_mapped(zones[d])]
            return "D-pad: " + ("; ".join(parts) or "not mapped")
        if kind == "stick":
            cfg = profile["sticks"][name]
            label = model.STICK_LABELS[name]
            if cfg["mode"] == "mouse":
                return f"{label}: mouse ({cfg['mouse']['speed']:.0f} px/s)"
            parts = [f"{model.DIRECTION_ARROWS.get(z, 'outer')} {model.describe_slot(s)}"
                     for z, s in cfg["zones"].items() if model.slot_is_mapped(s)]
            return f"{label}: " + ("; ".join(parts) or "not mapped")
        zones = profile["triggers"][name]["zones"]
        return (f"{model.TRIGGER_LABELS[name]}: activation {model.describe_slot(zones['soft'])}; "
                f"full {model.describe_slot(zones['full'])}")

    def _hover(self, cid: str | None) -> None:
        text = "Click a control to edit it"
        if cid is not None and self._profile is not None:
            text = self._summary(cid)
        self.itemconfigure(self._status, text=text)

    # --- live input --------------------------------------------------------------

    def update_live(self, preview: dict | None) -> None:
        p = palette()
        pressed = set(preview["pressed"]) if preview else set()
        results = preview["results"] if preview else {}
        for cid, items in self._shapes.items():
            kind, _, name = cid.partition(":")
            for item in items:
                if kind == "button":
                    on = name in pressed
                elif kind == "dpad":
                    zone = next(t.split(":")[1] for t in self.gettags(item) if t.startswith("zone:"))
                    on = DPAD_ARMS[zone][1] in pressed
                elif kind == "stick":
                    on = bool(results.get(name) and results[name].active)
                else:
                    on = False
                base = p["body"] if cid in ("button:ls", "button:rs") else p["control"]
                self._fill(item, p["pressed"] if on else base)
        for stick, (cx, cy) in STICK_CENTRES.items():
            result = results.get(stick)
            x, y = result.raw if result is not None else (0.0, 0.0)
            ox, oy = cx + x * (STICK_RADIUS - STICK_KNOB), cy + y * (STICK_RADIUS - STICK_KNOB)
            knob, text = self._knobs[stick]
            k = STICK_KNOB
            self.coords(knob, ox - k, oy - k, ox + k, oy + k)
            self.coords(text, ox, oy)
        for trigger, item in self._trigger_fill.items():
            result = results.get(trigger)
            x0, y0, x1, y1 = TRIGGER_RECTS[trigger]
            level = result.raw if result is not None else 0.0
            self.coords(item, x0, y0, x0 + (x1 - x0) * level, y1)
            self.tag_raise(self._labels[f"trigger:{trigger}"])

    def _fill(self, item: int, color: str) -> None:
        if self._fills.get(item) != color:
            self._fills[item] = color
            self.itemconfigure(item, fill=color)
