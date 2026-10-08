"""Modal dialogs. Every dialog that captures keyboard input pauses injection
while it is open (and resumes it as soon as it closes), so a held synthetic
key can never type into the dialog."""

from __future__ import annotations

import sys
import time
import tkinter as tk
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import customtkinter as ctk

from app import keys, layouts
from app.profiles import ProfileError


@contextmanager
def injection_paused(engine) -> Iterator[None]:
    """For native modal dialogs (message boxes, file pickers)."""
    engine.pause("dialog")
    try:
        yield
    finally:
        engine.resume("dialog")


class ModalDialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, engine) -> None:
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self._engine = engine
        self._resumed = False
        engine.pause("dialog")
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.after(20, self._activate)

    def _activate(self) -> None:
        if not self.winfo_exists():
            return
        try:
            self.grab_set()
        except tk.TclError:  # not viewable yet
            self.after(50, self._activate)
            return
        self._center()
        # The user just clicked inside this app, so it already owns the
        # foreground; focusing our own dialog never steals focus elsewhere.
        self.focus_force()
        icon = getattr(self.master, "window_icon", None)
        if icon is not None:
            self.after(250, lambda: self.winfo_exists() and self.iconphoto(False, icon))

    def _center(self) -> None:
        self.update_idletasks()
        master = self.master
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _on_destroy(self, event) -> None:
        if event.widget is self and not self._resumed:
            self._resumed = True
            self._engine.resume("dialog")

    def cancel(self) -> None:
        self.result = None
        self.destroy()

    def finish(self, result) -> None:
        self.result = result
        self.destroy()

    def show(self):
        self.master.wait_window(self)
        return self.result


class KeyCaptureDialog(ModalDialog):
    """Records the next key or chord, e.g. ["ctrl", "shift", "s"]."""

    def __init__(self, master, engine) -> None:
        super().__init__(master, "Capture key", engine)
        ctk.CTkLabel(self, justify="left", text=(
            "Press a key or key combination.\n"
            "A modifier on its own (e.g. Shift) is captured when released.")
        ).pack(padx=24, pady=(20, 8))
        self._live = ctk.CTkLabel(self, text="...", font=ctk.CTkFont(size=20, weight="bold"))
        self._live.pack(pady=8)
        ctk.CTkButton(self, text="Cancel", width=100, command=self.cancel).pack(pady=(8, 20))
        self._modifiers: list[str] = []
        self.bind("<KeyPress>", self._on_press)
        self.bind("<KeyRelease>", self._on_release)

    def _key_name(self, event) -> str | None:
        return keys.name_from_tk(event.keysym, event.keycode, sys.platform == "win32")

    def _on_press(self, event) -> str:
        name = self._key_name(event)
        if name is None:
            return "break"
        if keys.is_modifier(name):
            if name not in self._modifiers:
                self._modifiers.append(name)
                self._live.configure(text=keys.format_chord(self._modifiers) + " + ...")
            return "break"
        self.finish(self._modifiers + [name])
        return "break"

    def _on_release(self, event) -> str:
        name = self._key_name(event)
        if name is not None and keys.is_modifier(name) and self._modifiers:
            self.finish(list(self._modifiers))
        return "break"


class DetectDialog(ModalDialog):
    """Waits for the user to actuate a control and returns the raw binding.

    Result: a binding dict, "unbind", or None when cancelled.
    """

    TIMEOUT_S = 10.0

    def __init__(self, master, engine, instance_id: int, control: str) -> None:
        super().__init__(master, "Detect input", engine)
        self._instance_id, self._control = instance_id, control
        self._baseline: dict | None = None
        self._started = time.monotonic()
        default = f"Press {layouts.CONTROL_LABELS[control]}"
        ctk.CTkLabel(self, text=layouts.DETECT_PROMPTS.get(control, default),
                     font=ctk.CTkFont(size=15, weight="bold")).pack(padx=24, pady=(20, 4))
        self._status = ctk.CTkLabel(self, text="Keep everything else at rest...")
        self._status.pack(padx=24, pady=4)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=(8, 20))
        ctk.CTkButton(row, text="Unbind", width=100,
                      command=lambda: self.finish("unbind")).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Cancel", width=100, command=self.cancel).pack(side="left", padx=6)
        self.bind("<Escape>", lambda _e: self.cancel())
        self.after(300, self._take_baseline)

    def _raw(self) -> dict | None:
        preview = self._engine.snapshot()["preview"].get(self._instance_id)
        return preview["raw"] if preview else None

    def _take_baseline(self) -> None:
        if not self.winfo_exists():
            return
        self._baseline = self._raw()
        if self._baseline is None:
            self._status.configure(text="The controller is not connected.")
            return
        self._status.configure(text="Waiting for input...")
        self.after(30, self._poll)

    def _poll(self) -> None:
        if not self.winfo_exists():
            return
        raw = self._raw()
        if raw is None:
            self._status.configure(text="The controller was disconnected.")
            return
        binding = layouts.detect_binding(self._control, self._baseline, raw)
        if binding is not None:
            self.finish(binding)
        elif time.monotonic() - self._started > self.TIMEOUT_S:
            self._status.configure(text="Nothing detected. Cancel and try again.")
        else:
            self.after(30, self._poll)


class NameDialog(ModalDialog):
    """Asks for a profile name (and optionally a template); `submit` may raise ProfileError."""

    def __init__(self, master, engine, title: str, prompt: str, initial: str,
                 submit: Callable[[str, str | None], object],
                 templates: tuple[str, ...] | None = None) -> None:
        super().__init__(master, title, engine)
        self._submit = submit
        ctk.CTkLabel(self, text=prompt, anchor="w").pack(fill="x", padx=20, pady=(18, 4))
        self._name_var = ctk.StringVar(value=initial)
        entry = ctk.CTkEntry(self, textvariable=self._name_var, width=320)
        entry.pack(padx=20, pady=4)
        self._template = ctk.StringVar(value=templates[-1] if templates else "")
        if templates:
            ctk.CTkLabel(self, text="Start from template", anchor="w").pack(fill="x", padx=20, pady=(10, 4))
            ctk.CTkOptionMenu(self, values=list(templates), variable=self._template,
                              width=320).pack(padx=20)
        self._error = ctk.CTkLabel(self, text="", text_color="#e74c3c", anchor="w")
        self._error.pack(fill="x", padx=20, pady=(6, 0))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=(6, 18))
        ctk.CTkButton(row, text="OK", width=100, command=self._ok).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Cancel", width=100, command=self.cancel).pack(side="left", padx=6)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.cancel())
        self.after(60, lambda: entry.winfo_exists() and (entry.focus_set(), entry.select_range(0, "end")))

    def _ok(self) -> None:
        try:
            result = self._submit(self._name_var.get(), self._template.get() or None)
        except ProfileError as exc:
            self._error.configure(text=str(exc))
            return
        self.finish(result)
