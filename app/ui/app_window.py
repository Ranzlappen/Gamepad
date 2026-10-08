"""Main window: wires settings, profile storage, the mapping engine and the tray together."""

from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import ImageTk

from app import defaults, logging_setup, paths, settings as settings_module
from app.engine import MappingEngine
from app.logging_setup import log
from app.profiles import ProfileError, ProfileStore, slugify
from app.settings import Settings
from app.tray import Tray, TrayHandlers, make_icon
from app.ui.control_editors import ButtonEditor, DpadEditor, StickEditor, TriggerEditor
from app.ui.controller_view import ControllerView
from app.ui.devices_panel import DevicesPanel
from app.ui.dialogs import DetectDialog, KeyCaptureDialog, NameDialog, injection_paused
from app.ui.settings_panel import SettingsPanel

UI_QUEUE_MS = 30
LIVE_MS = 33
SAVE_DELAY_MS = 400
STATUS_EVERY = 15  # live ticks between status-bar refreshes
PANEL_COLOR = ("#dbdbdb", "#2b2b2b")  # matches widgets.palette()["panel"]


class MainWindow(ctk.CTk):
    def __init__(self, settings: Settings, store: ProfileStore, engine: MappingEngine) -> None:
        super().__init__()
        self.settings, self.store, self.engine = settings, store, engine
        self.devices: list[dict] = []
        self.selected_iid: int | None = None
        self.selected_control = "button:a"
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._save_job: str | None = None
        self._devices_version = -1
        self._last_paused: bool | None = None
        self._user_paused = False
        self._exiting = False
        self._status_countdown = 0
        self._last_live_error = 0.0
        self._active_editor = None
        self.profile = self._initial_profile()

        self.title(paths.APP_NAME)
        self.geometry("1240x780")
        self.minsize(1100, 660)
        self.window_icon = ImageTk.PhotoImage(make_icon(False))
        self.after(300, lambda: self.iconphoto(True, self.window_icon))  # after CTk's own icon
        self._build()

        self.tray = Tray(TrayHandlers(
            toggle_window=lambda: self.post(self.toggle_window),
            toggle_pause=lambda: self.post(self.toggle_pause),
            select_profile=lambda name: self.post(self.switch_profile, name),
            open_profiles_folder=lambda: self.post(self.open_folder, self.store.directory),
            exit_app=lambda: self.post(self.exit_app),
        ))
        tray_ok = self.tray.start()

        engine.on_calibrated = lambda result: self.post(self._on_calibrated, result)
        engine.set_polling_rate(settings.polling_hz)
        engine.set_mouse_sensitivity(settings.mouse_sensitivity)
        engine.set_layouts(settings.layouts)
        engine.set_profile(self.profile)
        engine.start()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.report_callback_exception = self._on_tk_exception
        self._refresh_profile_widgets()
        if settings.start_minimized and tray_ok:
            self.withdraw()
        self.after(UI_QUEUE_MS, self._drain_queue)
        self.after(LIVE_MS, self._live_tick)

    # --- layout ------------------------------------------------------------------

    def _build(self) -> None:
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(top, text="Profile").pack(side="left", padx=(12, 6), pady=8)
        self.profile_menu = ctk.CTkOptionMenu(top, values=[self.profile["name"]], width=220,
                                              dynamic_resizing=False, command=self.switch_profile)
        self.profile_menu.pack(side="left")
        for text, command in (("New", self.new_profile), ("Duplicate", self.duplicate_profile),
                              ("Rename", self.rename_profile), ("Delete", self.delete_profile),
                              ("Import", self.import_profile), ("Export", self.export_profile)):
            ctk.CTkButton(top, text=text, width=78, command=command).pack(side="left", padx=3)
        self.pause_button = ctk.CTkButton(top, text="Pause mapping", width=140,
                                          command=self.toggle_pause)
        self.pause_button.pack(side="right", padx=10)

        self.device_label = ctk.CTkLabel(self, text="", anchor="w")
        self.device_label.pack(fill="x", padx=16, pady=(6, 0))

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        mapping = self.tabs.add("Mapping")
        controllers = self.tabs.add("Controllers")
        settings_tab = self.tabs.add("Settings")

        left = ctk.CTkFrame(mapping, fg_color=PANEL_COLOR)
        left.pack(side="left", fill="y", padx=(0, 8))
        self.controller_view = ControllerView(left, self.select_control)
        self.controller_view.pack(padx=8, pady=(8, 2))
        ctk.CTkLabel(left, text="Mapped controls have blue labels; live input lights up green.",
                     text_color="gray").pack(pady=(0, 8))
        self.editor_frame = ctk.CTkScrollableFrame(mapping, fg_color=PANEL_COLOR)
        self.editor_frame.pack(side="left", fill="both", expand=True)
        capture = self.capture_key
        self.editors = {
            "button": ButtonEditor(self.editor_frame, self.profile_changed, capture),
            "dpad": DpadEditor(self.editor_frame, self.profile_changed, capture),
            "stick": StickEditor(self.editor_frame, self.profile_changed, capture),
            "trigger": TriggerEditor(self.editor_frame, self.profile_changed, capture),
        }
        self.devices_panel = DevicesPanel(controllers, self)
        self.devices_panel.pack(fill="both", expand=True)
        self.settings_panel = SettingsPanel(settings_tab, self)
        self.settings_panel.pack(fill="both", expand=True)

        self.status = ctk.CTkLabel(self, text="", anchor="w", text_color="gray")
        self.status.pack(fill="x", padx=16, pady=(0, 8))

    # --- threading helpers ---------------------------------------------------------

    def post(self, fn, *args) -> None:
        """Thread-safe: run fn(*args) on the Tk thread (tray and engine callbacks)."""
        self._queue.put((fn, args))

    def _drain_queue(self) -> None:
        while True:
            try:
                fn, args = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:
                log.exception("UI task failed")
        if not self._exiting:
            self.after(UI_QUEUE_MS, self._drain_queue)

    def _on_tk_exception(self, exc_type, value, tb) -> None:
        log.error("Unhandled UI error", exc_info=(exc_type, value, tb))
        self.show_message(f"Unexpected error: {value}", error=True)

    # --- live updates ------------------------------------------------------------

    def _live_tick(self) -> None:
        if self._exiting:
            return
        try:
            snap = self.engine.snapshot()
            if snap["devices_version"] != self._devices_version:
                self._devices_version = snap["devices_version"]
                self._devices_changed(snap["devices"])
            if snap["paused"] != self._last_paused:
                self._last_paused = snap["paused"]
                self._update_pause_widgets()
            if self.state() != "withdrawn":  # no drawing while hidden in the tray
                preview = snap["preview"].get(self.selected_iid)
                self.controller_view.update_live(preview)
                if self._active_editor is not None:
                    self._active_editor.update_live(preview)
                self.devices_panel.update_live(snap)
                self._status_countdown -= 1
                if self._status_countdown <= 0 or snap["error"]:
                    self._status_countdown = STATUS_EVERY
                    self._update_status(snap)
        except Exception:
            now = time.monotonic()
            if now - self._last_live_error > 5.0:  # do not flood the log at 30 Hz
                self._last_live_error = now
                log.exception("Live update failed")
        self.after(LIVE_MS, self._live_tick)

    def _devices_changed(self, devices: list[dict]) -> None:
        self.devices = devices
        ids = [d["instance_id"] for d in devices]
        if self.selected_iid not in ids:
            self.selected_iid = ids[0] if ids else None
        self.devices_panel.refresh_devices()
        self._update_device_label()

    def _update_device_label(self) -> None:
        device = self.selected_device()
        if device is None:
            text = "No controller connected. Plug one in; it is detected automatically."
        else:
            text = (f"Active controller: P{device['player']}  {device['name']}   GUID {device['guid']}"
                    f"   {device['axes']} axes, {device['buttons']} buttons, {device['hats']} hats")
            if len(self.devices) > 1:
                text += f"   ({len(self.devices)} connected)"
        self.device_label.configure(text=text)

    def _update_status(self, snap: dict) -> None:
        if snap["error"]:
            self.show_message(snap["error"], error=True)
            return
        stats = snap["stats"]
        parts = [f"Profile: {self.profile['name']}",
                 "Mapping PAUSED" if snap["paused"] else "Mapping active"]
        if stats:
            parts.append(f"{stats['hz']:.0f}/{stats['target_hz']} Hz, loop {stats['work_ms']:.2f} ms, "
                         f"max interval {stats['max_interval_ms']:.1f} ms")
        if snap["held"]:
            parts.append("holding " + ", ".join(snap["held"][:6]))
        self.status.configure(text="   |   ".join(parts), text_color="gray")

    def show_message(self, text: str, error: bool = False) -> None:
        self._status_countdown = STATUS_EVERY * 4  # keep the message visible for a few seconds
        self.status.configure(text=text, text_color="#e74c3c" if error else ("gray10", "gray90"))

    # --- selection and editing ---------------------------------------------------

    def selected_device(self) -> dict | None:
        return next((d for d in self.devices if d["instance_id"] == self.selected_iid), None)

    def select_device(self, instance_id: int) -> None:
        self.selected_iid = instance_id
        self.devices_panel.refresh_profile()
        self.devices_panel.refresh_layout()
        self._update_device_label()

    def select_control(self, control_id: str, zone: str | None = None) -> None:
        self._flush_edits()
        self.selected_control = control_id
        self.controller_view.select(control_id)
        editor = self.editors[control_id.split(":")[0]]
        if editor is not self._active_editor:
            if self._active_editor is not None:
                self._active_editor.pack_forget()
            editor.pack(fill="x", padx=8, pady=8)
            self._active_editor = editor
        editor.load(self.profile, control_id, zone)
        with contextlib.suppress(AttributeError, tk.TclError):
            self.editor_frame._parent_canvas.yview_moveto(0)  # scroll the editor back to the top

    def _flush_edits(self) -> None:
        """Commit a half-typed number or key before the editor switches targets."""
        try:
            widget = self.focus_get()
        except (KeyError, tk.TclError):  # Tk quirk while a dropdown is open
            widget = None
        if isinstance(widget, tk.Entry):
            widget.event_generate("<FocusOut>")
            self.focus_set()  # in-app focus only (no focus_force): never takes focus from other apps

    def profile_changed(self) -> None:
        """Any edit: apply to the engine immediately, save to disk shortly after."""
        self.engine.set_profile(self.profile)
        self.controller_view.set_profile(self.profile)
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(SAVE_DELAY_MS, self._save_now)

    def _save_now(self) -> None:
        if self._save_job is not None:
            self.after_cancel(self._save_job)
            self._save_job = None
        try:
            self.store.save(self.profile)
        except ProfileError as exc:
            self.show_message(str(exc), error=True)

    def capture_key(self) -> list[str] | None:
        return KeyCaptureDialog(self, self.engine).show()

    # --- profiles ------------------------------------------------------------------

    def _initial_profile(self) -> dict:
        names = self.store.names()
        preferred = [self.store.find(self.settings.active_profile), defaults.DESKTOP, *names]
        for name in preferred:
            if name and self.store.find(name):
                try:
                    return self.store.load(self.store.find(name))
                except ProfileError as exc:
                    log.warning("%s", exc)
        return self.store.create(self.store.unique_name(defaults.EMPTY), defaults.EMPTY,
                                 self.settings.default_deadzone, self.settings.default_anti_drift)

    def switch_profile(self, name: str) -> None:
        if name == self.profile["name"]:
            return
        self._flush_edits()
        self._save_now()
        try:
            profile = self.store.load(name)
        except ProfileError as exc:
            self.show_message(str(exc), error=True)
            self._refresh_profile_widgets()
            return
        self._activate(profile)

    def _activate(self, profile: dict) -> None:
        self.profile = profile
        self.settings.active_profile = profile["name"]
        self.settings.save()
        self.engine.set_profile(profile)  # the engine releases held keys before applying it
        self._refresh_profile_widgets()

    def _refresh_profile_widgets(self) -> None:
        self.profile_menu.configure(values=self.store.names())
        self.profile_menu.set(self.profile["name"])
        self.controller_view.set_profile(self.profile)
        self.select_control(self.selected_control)
        self.devices_panel.refresh_profile()
        self._update_pause_widgets()

    def _prepare_profile_op(self) -> None:
        self._flush_edits()
        self._save_now()

    def new_profile(self) -> None:
        self._prepare_profile_op()

        def submit(name: str, template: str | None) -> dict:
            return self.store.create(name, template or defaults.EMPTY,
                                     self.settings.default_deadzone, self.settings.default_anti_drift)

        profile = NameDialog(self, self.engine, "New profile", "Profile name",
                             self.store.unique_name("New profile"), submit,
                             templates=defaults.TEMPLATE_NAMES).show()
        if profile:
            self._activate(profile)

    def duplicate_profile(self) -> None:
        self._prepare_profile_op()
        source = self.profile["name"]
        profile = NameDialog(self, self.engine, "Duplicate profile", "Name of the copy",
                             self.store.unique_name(f"{source} copy"),
                             lambda name, _t: self.store.duplicate(source, name)).show()
        if profile:
            self._activate(profile)

    def rename_profile(self) -> None:
        self._prepare_profile_op()
        old = self.profile["name"]
        profile = NameDialog(self, self.engine, "Rename profile", "New name", old,
                             lambda name, _t: self.store.rename(old, name)).show()
        if profile:
            self._activate(profile)

    def delete_profile(self) -> None:
        self._prepare_profile_op()
        name = self.profile["name"]
        if len(self.store.names()) <= 1:
            self.show_message("At least one profile must remain.", error=True)
            return
        with injection_paused(self.engine):
            if not messagebox.askyesno("Delete profile", f"Delete the profile '{name}'?", parent=self):
                return
        try:
            self.store.delete(name)
            self._activate(self.store.load(self.store.names()[0]))
        except ProfileError as exc:
            self.show_message(str(exc), error=True)

    def import_profile(self) -> None:
        self._prepare_profile_op()
        with injection_paused(self.engine):
            path = filedialog.askopenfilename(parent=self, title="Import profile",
                                              filetypes=[("Profile", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            self._activate(self.store.import_file(Path(path)))
            self.show_message(f"Imported '{self.profile['name']}'.")
        except ProfileError as exc:
            self.show_message(str(exc), error=True)

    def export_profile(self) -> None:
        self._prepare_profile_op()
        name = self.profile["name"]
        with injection_paused(self.engine):
            path = filedialog.asksaveasfilename(parent=self, title="Export profile",
                                                initialfile=f"{slugify(name)}.json",
                                                defaultextension=".json",
                                                filetypes=[("Profile", "*.json")])
        if not path:
            return
        try:
            self.store.export(name, Path(path))
            self.show_message(f"Exported '{name}' to {path}")
        except ProfileError as exc:
            self.show_message(str(exc), error=True)

    # --- controllers ---------------------------------------------------------------

    def _on_calibrated(self, result: dict) -> None:
        if not result.get("ok"):
            self.devices_panel.calibration_done(result.get("error", "Calibration failed."), error=True)
            return
        entry = self.profile["calibration"].setdefault(result["guid"], {"axes": {}})
        entry["axes"].update({str(i): v for i, v in result["axes"].items()})
        entry["device"] = result["device"]
        entry["updated"] = datetime.now().isoformat(sep=" ", timespec="seconds")
        self.profile_changed()  # only calibration changes; every mapping is kept
        message = f"Calibrated {len(result['axes'])} axes of '{result['device']}'."
        if result["warnings"]:
            message += " " + " ".join(result["warnings"])
        self.devices_panel.calibration_done(message, error=bool(result["warnings"]))

    def detect_binding(self, control: str) -> None:
        device = self.selected_device()
        if device is None:
            return
        result = DetectDialog(self, self.engine, device["instance_id"], control).show()
        if result == "unbind":
            self._layout_entry(device["guid"]).setdefault("bindings", {})[control] = None
        elif result:
            self._layout_entry(device["guid"]).setdefault("bindings", {})[control] = result
        else:
            return
        self._layouts_changed()

    def set_layout_preset(self, guid: str, preset: str) -> None:
        self._layout_entry(guid)["preset"] = preset
        self._layouts_changed()

    def reset_layout_binding(self, guid: str, control: str | None) -> None:
        bindings = self._layout_entry(guid).setdefault("bindings", {})
        if control is None:
            bindings.clear()
        else:
            bindings.pop(control, None)
        self._layouts_changed()

    def _layout_entry(self, guid: str) -> dict:
        return self.settings.layouts.setdefault(guid, {"preset": "auto", "bindings": {}})

    def _layouts_changed(self) -> None:
        self.settings.save()
        self.engine.set_layouts(self.settings.layouts)
        self.devices_panel.refresh_layout()

    # --- settings ------------------------------------------------------------------

    def apply_setting(self, name: str, value) -> None:
        s = self.settings
        if name == "start_with_windows":
            ok = settings_module.set_start_with_windows(bool(value))
            s.start_with_windows = bool(value) if ok else settings_module.is_start_with_windows()
            if not ok:
                self.show_message("Could not update the Windows startup entry.", error=True)
                self.settings_panel.sync(name)
        else:
            setattr(s, name, value)
        if name == "polling_hz":
            self.engine.set_polling_rate(value)
        elif name == "mouse_sensitivity":
            self.engine.set_mouse_sensitivity(value)
        elif name == "debug_logging":
            logging_setup.set_debug(bool(value))
        elif name == "theme":
            ctk.set_appearance_mode(value)
            self.after(50, self.controller_view.redraw)
        s.save()

    # --- window, tray and exit -----------------------------------------------------

    def _update_pause_widgets(self) -> None:
        paused = self.engine.is_paused()
        self.pause_button.configure(text="Resume mapping" if self._user_paused else "Pause mapping")
        self.tray.update(paused, self._user_paused, self.store.names(), self.profile["name"])

    def toggle_pause(self) -> None:
        self._user_paused = not self._user_paused
        self.engine.set_user_paused(self._user_paused)
        self._update_pause_widgets()

    def toggle_window(self) -> None:
        if self.state() in ("withdrawn", "iconic"):
            self.deiconify()  # requested by the user from the tray menu
            self.lift()
        else:
            self.withdraw()

    def on_close(self) -> None:
        if self.settings.close_to_tray and self.tray.running:
            self.withdraw()
        else:
            self.exit_app()

    def open_folder(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606 - opens Explorer on our own folder
        else:
            subprocess.Popen(["xdg-open", str(folder)])  # noqa: S603, S607

    def exit_app(self) -> None:
        if self._exiting:
            return
        self._exiting = True
        try:
            self._flush_edits()
            self._save_now()
            self.settings.save()
        finally:
            self.tray.stop()
            self.engine.stop()  # releases every held key, stops the thread, quits pygame
            self.destroy()


def run() -> int:
    settings = Settings.load()
    logging_setup.configure(settings.debug_logging)
    ctk.set_appearance_mode(settings.theme)
    store = ProfileStore(paths.profiles_dir())
    created = store.ensure_defaults(first_run=not settings.first_run_done)
    if created:
        log.info("Created default profiles: %s", ", ".join(created))
    settings.first_run_done = True
    if sys.platform == "win32":  # the Run key may have been edited outside the app
        settings.start_with_windows = settings_module.is_start_with_windows()
    settings.save()
    engine = MappingEngine()
    try:
        window = MainWindow(settings, store, engine)
        window.mainloop()
    finally:
        engine.stop()
    return 0
