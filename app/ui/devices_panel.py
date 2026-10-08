"""Controllers tab: connected devices, calibration, anti-drift and input layout."""

from __future__ import annotations

import customtkinter as ctk

from app import layouts
from app.ui.widgets import NumberField, section

ERROR_COLOR = "#e74c3c"


class DevicesPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self._app = app
        self._rows: dict[str, tuple[ctk.CTkLabel, ctk.CTkButton, ctk.CTkButton]] = {}

        section(self, "Connected controllers (up to 4)").pack(fill="x", pady=(4, 2))
        self._selected = ctk.IntVar(value=-1)
        self._device_list = ctk.CTkFrame(self, fg_color="transparent")
        self._device_list.pack(fill="x")

        section(self, "Calibration").pack(fill="x", pady=(16, 2))
        ctk.CTkLabel(self, anchor="w", justify="left", wraplength=640, text=(
            "Leave both sticks centred and both triggers released, then click Calibrate. "
            "The resting position is sampled for 2 seconds and stored as per-axis offsets "
            "in the active profile. Mappings are not changed; recalibrate at any time.")
        ).pack(fill="x")
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=6)
        self._calibrate = ctk.CTkButton(row, text="Calibrate selected controller", width=220,
                                        command=self._start_calibration)
        self._calibrate.pack(side="left")
        self._progress = ctk.CTkProgressBar(row, width=220)
        self._progress.set(0)
        self._progress.pack(side="left", padx=12)
        self._cal_status = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=640)
        self._cal_status.pack(fill="x")

        section(self, "Anti-drift (active profile)").pack(fill="x", pady=(16, 2))
        self._drift_fields = [
            NumberField(self, "Anti-drift deadzone", self._drift_getter("threshold"),
                        self._drift_setter("threshold"), 0.0, 0.5, percent=True, label_width=170),
            NumberField(self, "Recentre after", self._drift_getter("delay_ms"),
                        self._drift_setter("delay_ms"), 0, 2000, unit="ms", label_width=170),
        ]
        for field in self._drift_fields:
            field.pack(fill="x", pady=2)
        ctk.CTkLabel(self, anchor="w", justify="left", wraplength=640, text_color="gray", text=(
            "After calibration, any axis that stays below the anti-drift deadzone for longer "
            "than the delay is snapped back to exactly zero.")).pack(fill="x")

        section(self, "Input layout (selected controller)").pack(fill="x", pady=(16, 2))
        ctk.CTkLabel(self, anchor="w", justify="left", wraplength=640, text_color="gray", text=(
            "Which raw button, axis or hat drives each control. Auto-detect suits Xbox-style "
            "and PlayStation/Switch Pro controllers; use Detect for anything that lands on the "
            "wrong control. Layouts are stored per controller model (GUID).")).pack(fill="x")
        preset_row = ctk.CTkFrame(self, fg_color="transparent")
        preset_row.pack(fill="x", pady=6)
        ctk.CTkLabel(preset_row, text="Preset", width=80, anchor="w").pack(side="left")
        self._preset = ctk.CTkOptionMenu(preset_row, values=list(layouts.PRESET_LABELS.values()),
                                         width=300, command=self._on_preset)
        self._preset.pack(side="left")
        ctk.CTkButton(preset_row, text="Reset all bindings", width=150,
                      command=lambda: self._reset_binding(None)).pack(side="left", padx=10)
        table = ctk.CTkFrame(self)
        table.pack(fill="x", pady=(0, 10))
        for i, control in enumerate(layouts.LAYOUT_CONTROLS):
            ctk.CTkLabel(table, text=layouts.CONTROL_LABELS[control], width=150,
                         anchor="w").grid(row=i, column=0, padx=(10, 4), pady=1, sticky="w")
            value = ctk.CTkLabel(table, text="", width=190, anchor="w")
            value.grid(row=i, column=1, padx=4, sticky="w")
            detect = ctk.CTkButton(table, text="Detect", width=70, height=24,
                                   command=lambda c=control: self._app.detect_binding(c))
            detect.grid(row=i, column=2, padx=4, pady=1)
            reset = ctk.CTkButton(table, text="Reset", width=60, height=24,
                                  command=lambda c=control: self._reset_binding(c))
            reset.grid(row=i, column=3, padx=(4, 10), pady=1)
            self._rows[control] = (value, detect, reset)

    # --- devices -------------------------------------------------------------------

    def refresh_devices(self) -> None:
        for child in self._device_list.winfo_children():
            child.destroy()
        devices = self._app.devices
        if not devices:
            ctk.CTkLabel(self._device_list, anchor="w", text=(
                "No controller detected. Plug one in; it is picked up automatically.")
            ).pack(fill="x", pady=4)
        self._selected.set(self._app.selected_iid if self._app.selected_iid is not None else -1)
        for device in devices:
            text = (f"P{device['player']}  {device['name']}\n"
                    f"GUID {device['guid']}\n"
                    f"{device['axes']} axes, {device['buttons']} buttons, {device['hats']} hats")
            ctk.CTkRadioButton(self._device_list, text=text, variable=self._selected,
                               value=device["instance_id"],
                               command=lambda i=device["instance_id"]: self._app.select_device(i)
                               ).pack(fill="x", pady=4, anchor="w")
        state = "normal" if devices else "disabled"
        self._calibrate.configure(state=state)
        self._preset.configure(state=state)
        for _value, detect, reset in self._rows.values():
            detect.configure(state=state)
            reset.configure(state=state)
        self.refresh_profile()
        self.refresh_layout()

    def refresh_profile(self) -> None:
        for field in self._drift_fields:
            field.refresh()
        device = self._app.selected_device()
        entry = self._app.profile["calibration"].get(device["guid"]) if device else None
        if device is None:
            text = ""
        elif entry:
            text = f"Calibrated {entry['updated'] or 'earlier'} ({len(entry['axes'])} axes) in this profile."
        else:
            text = "Not calibrated in this profile yet."
        self._cal_status.configure(text=text, text_color=("gray10", "gray90"))

    def refresh_layout(self) -> None:
        device = self._app.selected_device()
        if device is None:
            for value, _detect, _reset in self._rows.values():
                value.configure(text="-")
            return
        resolved = layouts.resolve(device["guid"], device["axes"], device["buttons"],
                                   device["hats"], self._app.settings.layouts)
        self._preset.set(layouts.PRESET_LABELS[resolved["preset"]])
        for control, (value, _detect, _reset) in self._rows.items():
            custom = " (custom)" if control in resolved["custom"] else ""
            value.configure(text=layouts.describe(resolved["bindings"].get(control)) + custom)

    def _on_preset(self, label: str) -> None:
        device = self._app.selected_device()
        if device is not None:
            preset = next(k for k, v in layouts.PRESET_LABELS.items() if v == label)
            self._app.set_layout_preset(device["guid"], preset)

    def _reset_binding(self, control: str | None) -> None:
        device = self._app.selected_device()
        if device is not None:
            self._app.reset_layout_binding(device["guid"], control)

    # --- calibration --------------------------------------------------------------

    def _start_calibration(self) -> None:
        device = self._app.selected_device()
        if device is None:
            return
        self._calibrate.configure(state="disabled")
        self._cal_status.configure(text="Calibrating... do not touch the controller.",
                                   text_color=("gray10", "gray90"))
        self._app.engine.request_calibration(device["instance_id"])

    def calibration_done(self, message: str, error: bool = False) -> None:
        self._calibrate.configure(state="normal" if self._app.devices else "disabled")
        self._progress.set(0)
        self._cal_status.configure(text=message,
                                   text_color=ERROR_COLOR if error else ("gray10", "gray90"))

    def update_live(self, snapshot: dict) -> None:
        preview = snapshot["preview"].get(self._app.selected_iid)
        progress = preview.get("calibrating") if preview else None
        if progress is not None:
            self._progress.set(progress)

    # --- helpers ------------------------------------------------------------------

    def _drift_getter(self, key: str):
        return lambda: self._app.profile["anti_drift"][key]  # active profile, read on every access

    def _drift_setter(self, key: str):
        def apply(value: float) -> None:
            drift = self._app.profile["anti_drift"]
            drift[key] = int(round(value)) if key == "delay_ms" else value
            self._app.profile_changed()
        return apply
