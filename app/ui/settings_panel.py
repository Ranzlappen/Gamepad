"""Settings tab: polling, defaults, sensitivity, startup, tray, theme and logging."""

from __future__ import annotations

import customtkinter as ctk

from app import paths
from app.settings import POLLING_RATES
from app.ui.widgets import NumberField, section

THEME_LABELS = {"dark": "Dark", "light": "Light"}


class SettingsPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self._app = app
        self._vars: dict[str, ctk.BooleanVar] = {}
        s = app.settings

        section(self, "Mapping").pack(fill="x", pady=(4, 2))
        row = self._row("Polling rate")
        rate = ctk.CTkOptionMenu(row, values=[f"{hz} Hz" for hz in POLLING_RATES], width=120,
                                 command=lambda v: app.apply_setting("polling_hz", int(v.split()[0])))
        rate.set(f"{s.polling_hz} Hz")
        rate.pack(side="left")
        ctk.CTkLabel(row, text="  250 Hz polls every 4 ms (target latency 8 ms or less).",
                     text_color="gray").pack(side="left")
        NumberField(self, "Mouse sensitivity", lambda: s.mouse_sensitivity,
                    lambda v: app.apply_setting("mouse_sensitivity", v), 0.1, 10.0,
                    decimals=2, unit="x", label_width=220).pack(fill="x", pady=2)

        section(self, "Defaults for new empty profiles").pack(fill="x", pady=(16, 2))
        NumberField(self, "Stick deadzone", lambda: s.default_deadzone,
                    lambda v: app.apply_setting("default_deadzone", v), 0.0, 0.9,
                    percent=True, label_width=220).pack(fill="x", pady=2)
        NumberField(self, "Anti-drift deadzone", lambda: s.default_anti_drift,
                    lambda v: app.apply_setting("default_anti_drift", v), 0.0, 0.5,
                    percent=True, label_width=220).pack(fill="x", pady=2)

        section(self, "Windows").pack(fill="x", pady=(16, 2))
        self._switch("Start with Windows (adds a per-user Run registry entry)", "start_with_windows")
        self._switch("Start minimized to the tray", "start_minimized")
        self._switch("Close button minimizes to the tray", "close_to_tray")

        section(self, "Appearance").pack(fill="x", pady=(16, 2))
        row = self._row("Theme")
        theme = ctk.CTkSegmentedButton(row, values=list(THEME_LABELS.values()),
                                       command=lambda v: app.apply_setting(
                                           "theme", next(k for k, t in THEME_LABELS.items() if t == v)))
        theme.set(THEME_LABELS[s.theme])
        theme.pack(side="left")

        section(self, "Diagnostics").pack(fill="x", pady=(16, 2))
        self._switch("Debug logging (rotating log in AppData)", "debug_logging")
        row = self._row("Log folder")
        ctk.CTkButton(row, text="Open", width=80,
                      command=lambda: app.open_folder(paths.log_dir())).pack(side="left")
        ctk.CTkLabel(row, text=f"  {paths.log_dir()}", text_color="gray").pack(side="left")
        ctk.CTkLabel(self, text=f"Settings file: {paths.settings_path()}", text_color="gray",
                     anchor="w").pack(fill="x", pady=(16, 0))

    def _row(self, label: str) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=label, width=220, anchor="w").pack(side="left")
        return row

    def _switch(self, text: str, name: str) -> None:
        var = ctk.BooleanVar(value=getattr(self._app.settings, name))
        self._vars[name] = var
        ctk.CTkSwitch(self, text=text, variable=var,
                      command=lambda: self._app.apply_setting(name, var.get())
                      ).pack(fill="x", pady=4, anchor="w")

    def sync(self, name: str) -> None:
        """Re-read a switch from settings (e.g. when the registry write failed)."""
        self._vars[name].set(getattr(self._app.settings, name))
