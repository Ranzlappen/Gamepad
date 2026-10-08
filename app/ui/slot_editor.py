"""Editors for one slot: press action, hold threshold, tap action and release action.

``host`` is the main window; it opens the modal dialogs: ``capture_key()``,
``pick_key(current)`` and ``edit_macro(steps)``.
"""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from app import keys, macros, model
from app.ui.widgets import NumberField

TYPE_LABELS = {"none": "No action", "key": "Keyboard key", "mouse_button": "Mouse button",
               "mouse_move": "Mouse movement", "macro": "Macro"}
MODE_LABELS = {"hold": "Hold", "tap": "Tap"}
BUTTON_LABELS = {"left": "Left", "right": "Right", "middle": "Middle", "x1": "Back (X1)", "x2": "Forward (X2)"}
DIRECTION_CHOICES = {f"{model.DIRECTION_ARROWS[d]} {model.DIRECTION_LABELS[d]}": d for d in model.DIRECTIONS}
ERROR_COLOR = "#e74c3c"


def _key_for(mapping: dict[str, str], label: str) -> str:
    return next(k for k, v in mapping.items() if v == label)


class ActionEditor(ctk.CTkFrame):
    """Edits one action dict in place and calls on_change after every edit."""

    def __init__(self, master, title: str, *, tap_only: bool, on_change: Callable[[], None],
                 host) -> None:
        super().__init__(master)
        self._tap_only = tap_only
        self._on_change = on_change
        self._host = host
        self._action: dict = model.no_action()
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(header, text=title, font=ctk.CTkFont(weight="bold")).pack(side="left")
        types = model.TAP_ACTION_TYPES if tap_only else model.ACTION_TYPES
        self._type_menu = ctk.CTkOptionMenu(header, values=[TYPE_LABELS[t] for t in types],
                                            width=160, command=self._on_type)
        self._type_menu.pack(side="right")
        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.pack(fill="x", padx=10, pady=(0, 8))

    def load(self, action: dict) -> None:
        self._action = action
        self._type_menu.set(TYPE_LABELS[action["type"]])
        self._build()

    def _changed(self) -> None:
        self._on_change()

    def _on_type(self, label: str) -> None:
        kind = _key_for(TYPE_LABELS, label)
        if kind == self._action["type"]:
            return
        replacement = model.default_action(kind, tap_only=self._tap_only)
        self._action.clear()
        self._action.update(replacement)
        self._build()
        self._changed()

    def _build(self) -> None:
        for child in self._body.winfo_children():
            child.destroy()
        kind = self._action["type"]
        if kind == "key":
            self._build_key()
        elif kind == "mouse_button":
            self._build_mouse_button()
        elif kind == "mouse_move":
            self._build_mouse_move()
        elif kind == "macro":
            self._build_macro()
        else:
            ctk.CTkLabel(self._body, text="Nothing happens.", text_color="gray").pack(anchor="w")

    def _mode_selector(self, row) -> None:
        if self._tap_only:
            ctk.CTkLabel(row, text="(tap)", text_color="gray").pack(side="left", padx=(8, 0))
            return
        selector = ctk.CTkSegmentedButton(row, values=list(MODE_LABELS.values()),
                                          command=self._on_mode, width=110)
        selector.set(MODE_LABELS[self._action["mode"]])
        selector.pack(side="left", padx=(8, 0))

    def _on_mode(self, label: str) -> None:
        self._action["mode"] = _key_for(MODE_LABELS, label)
        self._changed()

    def _build_key(self) -> None:
        # The closures bind this action and widget, so a late FocusOut after
        # the editor switched to another slot still commits to the right slot.
        action = self._action
        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(fill="x")
        box = ctk.CTkEntry(row, width=150)
        box.insert(0, "+".join(action["keys"]))
        box.pack(side="left")
        error = ctk.CTkLabel(self._body, text="", text_color=ERROR_COLOR, anchor="w")

        def show(names: list[str]) -> None:
            box.delete(0, "end")
            box.insert(0, "+".join(names))

        def commit(quiet: bool = False) -> None:
            if not box.winfo_exists():
                return
            try:
                names = keys.parse_chord(box.get())
            except ValueError as exc:
                if not quiet:
                    error.configure(text=str(exc))
                return
            error.configure(text="")
            if not quiet and box.get() != "+".join(names):
                show(names)
            if action.get("type") == "key" and names != action["keys"]:
                action["keys"] = names
                self._changed()

        def choose(dialog: Callable[[], list[str] | None]) -> None:
            names = dialog()
            if names and box.winfo_exists():
                show(names)
                commit()

        box.bind("<Return>", lambda _e: commit())
        box.bind("<FocusOut>", lambda _e: commit())
        box.bind("<KeyRelease>", lambda _e: commit(quiet=True))
        ctk.CTkButton(row, text="List...", width=56,
                      command=lambda: choose(lambda: self._host.pick_key(action["keys"]))
                      ).pack(side="left", padx=(6, 0))
        ctk.CTkButton(row, text="Capture...", width=76,
                      command=lambda: choose(self._host.capture_key)).pack(side="left", padx=(6, 0))
        self._mode_selector(row)
        error.pack(fill="x")
        ctk.CTkLabel(self._body, text="Type a key or chord (ctrl+shift+s), pick one from the list, "
                                      "or capture it", text_color="gray", anchor="w").pack(fill="x")

    def _build_macro(self) -> None:
        action = self._action  # bound like _build_key: edits always land on this action
        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text=macros.summary(action["steps"]).capitalize(), width=150,
                     anchor="w").pack(side="left")

        def edit() -> None:
            steps = self._host.edit_macro(action["steps"])
            if steps is not None and action.get("type") == "macro":
                action["steps"] = steps
                if self._action is action:
                    self._build()
                self._changed()

        ctk.CTkButton(row, text="Record / edit...", width=130, command=edit).pack(side="left")
        if action["steps"]:
            ctk.CTkLabel(self._body, text=macros.preview(action["steps"]), text_color="gray",
                         anchor="w", justify="left", wraplength=400).pack(fill="x", pady=(4, 0))
        if self._tap_only:
            ctk.CTkLabel(self._body, text="Runs once, to the end.", text_color="gray",
                         anchor="w").pack(fill="x")
            return
        loop = ctk.BooleanVar(value=action["loop"])

        def set_loop() -> None:
            action["loop"] = bool(loop.get())
            self._changed()

        ctk.CTkCheckBox(self._body, text="Repeat while held (otherwise it runs once, to the end)",
                        variable=loop, command=set_loop).pack(anchor="w", pady=(6, 0))

    def _build_mouse_button(self) -> None:
        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(fill="x")
        menu = ctk.CTkOptionMenu(row, values=list(BUTTON_LABELS.values()), width=140,
                                 command=self._on_mouse_button)
        menu.set(BUTTON_LABELS[self._action["button"]])
        menu.pack(side="left")
        self._mode_selector(row)

    def _on_mouse_button(self, label: str) -> None:
        self._action["button"] = _key_for(BUTTON_LABELS, label)
        self._changed()

    def _build_mouse_move(self) -> None:
        a = self._action
        row = ctk.CTkFrame(self._body, fg_color="transparent")
        row.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(row, text="Direction", width=150, anchor="w").pack(side="left")
        menu = ctk.CTkOptionMenu(row, values=list(DIRECTION_CHOICES), width=150,
                                 command=self._on_direction)
        menu.set(_key_for(DIRECTION_CHOICES, a["direction"]))
        menu.pack(side="left")
        NumberField(self._body, "Speed", lambda: a["speed"], self._setter(a, "speed"),
                    10, 5000, unit="px/s").pack(fill="x", pady=2)
        NumberField(self._body, "Acceleration", lambda: a["accel"], self._setter(a, "accel"),
                    0, 5, decimals=1, unit="x/s").pack(fill="x", pady=2)

    def _on_direction(self, label: str) -> None:
        self._action["direction"] = DIRECTION_CHOICES[label]
        self._changed()

    def _setter(self, action: dict, field: str) -> Callable[[float], None]:
        def apply(value: float) -> None:
            action[field] = value
            self._changed()
        return apply


class SlotEditor(ctk.CTkFrame):
    """Press / hold threshold / tap / release editors for one slot.

    With a layer, the slot is the layer's override: a checkbox creates or removes it,
    and without an override the base mapping is shown read-only.
    """

    def __init__(self, master, on_change: Callable[[], None], host) -> None:
        super().__init__(master, fg_color="transparent")
        self._on_change = on_change
        self._slot: dict = model.make_slot()
        self._base: dict = self._slot
        self._slot_id = ""
        self._title_text = ""
        self._layer: dict | None = None
        self._title = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=15, weight="bold"), anchor="w")
        self._title.pack(fill="x", pady=(4, 0))
        self._summary = ctk.CTkLabel(self, text="", text_color="gray", anchor="w", justify="left",
                                     wraplength=440)
        self._summary.pack(fill="x", pady=(0, 6))
        self._layer_row = ctk.CTkFrame(self)
        self._override_var = ctk.BooleanVar()
        self._override = ctk.CTkCheckBox(self._layer_row, text="Own mapping in this layer",
                                         variable=self._override_var, command=self._toggle_override)
        self._override.pack(anchor="w", padx=10, pady=(8, 2))
        self._layer_info = ctk.CTkLabel(self._layer_row, text="", text_color="gray", anchor="w",
                                        justify="left", wraplength=420)
        self._layer_info.pack(fill="x", padx=10, pady=(0, 8))
        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.pack(fill="x")
        self._press = ActionEditor(self._body, "On press", tap_only=False, on_change=self._changed,
                                   host=host)
        self._press.pack(fill="x", pady=3)
        self._hold = NumberField(self._body, "Hold threshold", lambda: self._slot["hold_ms"],
                                 self._set_hold, 0, 5000, unit="ms")
        self._hold.pack(fill="x", pady=(6, 0))
        self._hold_hint = ctk.CTkLabel(self._body, text="", text_color="gray", anchor="w", justify="left")
        self._hold_hint.pack(fill="x")
        self._tap = ActionEditor(self._body, "Short tap (released before the threshold)", tap_only=True,
                                 on_change=self._changed, host=host)
        self._release = ActionEditor(self._body, "On release", tap_only=True, on_change=self._changed,
                                     host=host)
        self._release.pack(fill="x", pady=3)

    def load(self, slot: dict, title: str, *, slot_id: str = "", layer: dict | None = None) -> None:
        """Edit `slot` (a base slot), or with `layer` the layer's override of `slot_id`."""
        self._base, self._title_text, self._slot_id, self._layer = slot, title, slot_id, layer
        if layer is None:
            self._layer_row.pack_forget()
            self._title.configure(text=title)
            self._edit(slot)
            return
        self._title.configure(text=f"{title}  -  layer \"{layer['name']}\"")
        self._layer_row.pack(fill="x", pady=(0, 6), after=self._summary)
        base_text = model.describe_slot(slot)
        if slot_id in model.layer_modifier_slots(layer):
            self._override.pack_forget()
            self._layer_info.configure(text=(
                "This control switches the layer on while held, so it always keeps its base "
                f"mapping ({base_text}). Edit it in the Base layer."))
            self._summary.configure(text=f"Base mapping: {base_text}")
            self._body.pack_forget()
            return
        self._override.pack(anchor="w", padx=10, pady=(8, 2), before=self._layer_info)
        override = layer["slots"].get(slot_id)
        self._override_var.set(override is not None)
        if override is None:
            self._layer_info.configure(text=(
                "Off: this control does what it does in the Base layer while the layer is "
                "active. Tick it to give it its own action here."))
            self._summary.configure(text=f"Uses the base mapping: {base_text}")
            self._body.pack_forget()
            return
        self._layer_info.configure(text="On: replaces the base mapping while the layer's "
                                        "modifiers are held.")
        self._edit(override)

    def _edit(self, slot: dict) -> None:
        self._slot = slot
        self._body.pack(fill="x")
        self._press.load(slot["press"])
        self._tap.load(slot["tap"])
        self._release.load(slot["release"])
        self._hold.refresh()
        self._layout_tap()
        self._summary.configure(text=model.describe_slot(slot))

    def _toggle_override(self) -> None:
        layer, slot_id = self._layer, self._slot_id
        if layer is None:
            return
        if self._override_var.get():
            layer["slots"][slot_id] = model.make_slot()
        else:
            layer["slots"].pop(slot_id, None)
        self.load(self._base, self._title_text, slot_id=slot_id, layer=layer)
        self._on_change()

    def _layout_tap(self) -> None:
        if self._slot["hold_ms"] > 0:
            self._hold_hint.configure(text="On press starts only after the threshold; "
                                           "shorter presses fire the tap action instead.")
            self._tap.pack(fill="x", pady=3, before=self._release)
        else:
            self._hold_hint.configure(text="0 ms: On press fires immediately. Set a threshold "
                                           "to give short taps their own action.")
            self._tap.pack_forget()

    def _set_hold(self, value: float) -> None:
        self._slot["hold_ms"] = int(round(value))
        self._layout_tap()
        self._changed()

    def _changed(self) -> None:
        self._summary.configure(text=model.describe_slot(self._slot))
        self._on_change()
