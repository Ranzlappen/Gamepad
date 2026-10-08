"""Modal dialogs. Every dialog that captures keyboard input pauses injection
while it is open (and resumes it as soon as it closes), so a held synthetic
key can never type into the dialog."""

from __future__ import annotations

import contextlib
import copy
import sys
import time
import tkinter as tk
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import customtkinter as ctk

from app import keys, layouts, macros, model
from app.profiles import ProfileError
from app.ui.widgets import palette

ERROR_COLOR = "#e74c3c"


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
        self.window_icon = getattr(master, "window_icon", None)  # nested dialogs inherit it
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
        icon = self.window_icon
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
        try:
            previous = self.grab_current()  # the dialog that opened this one, if any
        except (KeyError, tk.TclError):
            previous = None
        self.master.wait_window(self)
        if previous is not None:  # a nested dialog took the grab: hand it back
            with contextlib.suppress(tk.TclError):
                if previous.winfo_exists():
                    previous.grab_set()
        return self.result


def _listbox(master, height: int, width: int) -> tuple[tk.Listbox, ctk.CTkFrame]:
    """A native list (fast, scrolls with the mouse wheel) styled like the rest of the app."""
    p = palette()
    frame = ctk.CTkFrame(master, fg_color="transparent")
    listbox = tk.Listbox(frame, height=height, width=width, activestyle="none",
                         exportselection=False, borderwidth=0, highlightthickness=1,
                         background=p["panel"], foreground=p["text"],
                         highlightbackground=p["outline"], highlightcolor=p["mapped"],
                         selectbackground=p["mapped"], selectforeground="#ffffff",
                         font=("Segoe UI", 11))
    scrollbar = ctk.CTkScrollbar(frame, command=listbox.yview)
    listbox.configure(yscrollcommand=scrollbar.set)
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="left", fill="y")
    return listbox, frame


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


class KeyPickerDialog(ModalDialog):
    """Every key in a searchable list that scrolls with the mouse wheel; returns a chord."""

    CHORD_MODIFIERS = ("ctrl", "shift", "alt", "cmd")
    ALL = "All keys"

    def __init__(self, master, engine, current: list[str] | None = None) -> None:
        super().__init__(master, "Choose key", engine)
        current = list(current or [])
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(16, 6))
        self._search = ctk.CTkEntry(top, width=200, placeholder_text="Search, e.g. f5, page, num")
        self._search.pack(side="left")
        self._group = ctk.CTkOptionMenu(top, values=[self.ALL, *keys.KEY_GROUPS], width=190,
                                        command=lambda _value: self._filter())
        self._group.pack(side="left", padx=(8, 0))
        self._list, frame = _listbox(self, height=14, width=36)
        frame.pack(fill="both", padx=16)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkLabel(row, text="Together with").pack(side="left", padx=(0, 6))
        self._mods = {}
        for name in self.CHORD_MODIFIERS:
            var = ctk.BooleanVar(value=name in current)
            ctk.CTkCheckBox(row, text=keys.display_name(name), variable=var, width=64,
                            command=self._update_result).pack(side="left", padx=2)
            self._mods[name] = var
        self._result_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=15, weight="bold"))
        self._result_label.pack(pady=(8, 0))
        self._error = ctk.CTkLabel(self, text="", text_color=ERROR_COLOR)
        self._error.pack()
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(pady=(4, 16))
        ctk.CTkButton(buttons, text="OK", width=100, command=self._ok).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Cancel", width=100, command=self.cancel).pack(side="left", padx=6)
        self._shown: list[str] = []
        base = [k for k in current if k not in self.CHORD_MODIFIERS] or current[-1:]
        self._selected: str | None = base[-1] if base else None
        self._list.bind("<<ListboxSelect>>", self._on_select)
        self._list.bind("<Double-Button-1>", lambda _e: self._ok())
        self._list.bind("<Return>", lambda _e: self._ok())
        self._search.bind("<KeyRelease>", self._on_search_key)
        self._search.bind("<Return>", lambda _e: self._ok())
        self._search.bind("<Down>", lambda _e: self._focus_list())
        self.bind("<Escape>", lambda _e: self.cancel())
        self._filter()
        self.after(60, lambda: self._search.winfo_exists() and self._search.focus_set())

    def _on_search_key(self, event) -> None:
        if event.keysym not in ("Return", "Down", "Up", "Escape"):
            self._filter()

    def _filter(self) -> None:
        group = self._group.get()
        self._shown = keys.search(self._search.get(), None if group == self.ALL else group)
        self._list.delete(0, "end")
        for name in self._shown:
            shown = keys.display_name(name)
            self._list.insert("end", shown if shown.lower() == name else f"{shown}   ({name})")
        if self._selected in self._shown:
            index = self._shown.index(self._selected)
        elif self._shown and self._search.get().strip():
            index = 0  # best match of the search
        else:
            index = None
        if index is not None:
            self._list.selection_set(index)
            self._list.see(index)
            self._selected = self._shown[index]
        self._update_result()

    def _focus_list(self) -> None:
        self._list.focus_set()
        if self._shown and not self._list.curselection():
            self._list.selection_set(0)
            self._on_select()

    def _on_select(self, _event=None) -> None:
        selection = self._list.curselection()
        if selection:
            self._selected = self._shown[selection[0]]
        self._update_result()

    def _chord(self) -> list[str]:
        chord = [m for m, var in self._mods.items() if var.get() and m != self._selected]
        return chord + [self._selected] if self._selected else chord

    def _update_result(self) -> None:
        chord = self._chord()
        self._result_label.configure(text=keys.format_chord(chord) if chord else "Pick a key")
        self._error.configure(text="Use at most 4 keys in one chord" if len(chord) > 4 else "")

    def _ok(self) -> None:
        chord = self._chord()
        if chord and len(chord) <= 4:
            self.finish(chord)


class MacroDialog(ModalDialog):
    """Records keys and mouse clicks into a macro and edits its steps; returns the steps."""

    _MOUSE = {1: "left", 2: "middle", 3: "right"}
    _CLICKS = {"Left click": "left", "Right click": "right", "Middle click": "middle",
               "Back (X1)": "x1", "Forward (X2)": "x2"}

    def __init__(self, master, engine, steps: list[dict]) -> None:
        super().__init__(master, "Macro", engine)
        self._steps = copy.deepcopy(steps)
        self._recording = False
        self._events: list[tuple[int, str, str]] = []
        self._down: dict[str, str] = {}  # held while recording: name -> "key" | "button"
        self._pending_up: dict[str, int] = {}
        ctk.CTkLabel(self, anchor="w", justify="left", wraplength=560, text=(
            "Click Record, then type keys and click inside the box with the left, middle or "
            "right mouse button. Click Stop when done; recording replaces the steps. "
            "Controller mapping is paused while this window is open.")).pack(fill="x", padx=16, pady=(14, 6))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16)
        self._record_button = ctk.CTkButton(row, text="Record", width=110, fg_color="#c0392b",
                                            hover_color="#a93226", command=self._toggle_recording)
        self._record_button.pack(side="left")
        self._timing = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(row, text="Record delays (else 30 ms between steps)",
                        variable=self._timing).pack(side="left", padx=12)
        p = palette()
        self._pad = tk.Canvas(self, height=64, width=560, highlightthickness=2, takefocus=1,
                              background=p["body"], highlightbackground=p["outline"],
                              highlightcolor=p["outline"], cursor="hand2")
        self._pad.pack(padx=16, pady=8)
        self._pad_text = self._pad.create_text(280, 32, fill=p["text"], font=("Segoe UI", 11), text="")
        for event in ("<KeyPress>", "<KeyRelease>"):
            self._pad.bind(event, self._on_key)
        for number in self._MOUSE:
            self._pad.bind(f"<ButtonPress-{number}>", self._on_mouse)
            self._pad.bind(f"<ButtonRelease-{number}>", self._on_mouse)
        self._summary = ctk.CTkLabel(self, text="", anchor="w")
        self._summary.pack(fill="x", padx=16)
        self._list, frame = _listbox(self, height=12, width=60)
        frame.pack(fill="both", padx=16, pady=(2, 6))
        edit = ctk.CTkFrame(self, fg_color="transparent")
        edit.pack(fill="x", padx=16)
        for text, command in (("Add key tap...", self._add_key), ("Delete", self._delete),
                              ("Move up", lambda: self._move(-1)), ("Move down", lambda: self._move(1)),
                              ("Clear all", self._clear)):
            ctk.CTkButton(edit, text=text, width=96, command=command).pack(side="left", padx=(0, 6))
        click = ctk.CTkFrame(self, fg_color="transparent")
        click.pack(fill="x", padx=16, pady=(6, 0))
        self._click = ctk.CTkOptionMenu(click, values=list(self._CLICKS), width=150)
        self._click.pack(side="left")
        ctk.CTkButton(click, text="Add click", width=96, command=self._add_click).pack(side="left", padx=6)
        ctk.CTkLabel(click, text="Delay").pack(side="left", padx=(16, 4))
        self._delay = ctk.CTkEntry(click, width=60)
        self._delay.insert(0, "100")
        self._delay.pack(side="left")
        ctk.CTkLabel(click, text="ms").pack(side="left", padx=(4, 6))
        for text, command in (("Insert", self._add_delay), ("Set selected", self._set_delay),
                              ("Set all", self._set_all_delays)):
            ctk.CTkButton(click, text=text, width=84, command=command).pack(side="left", padx=(0, 6))
        self._error = ctk.CTkLabel(self, text="", text_color=ERROR_COLOR, anchor="w")
        self._error.pack(fill="x", padx=16)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(pady=(4, 16))
        ctk.CTkButton(buttons, text="OK", width=100, command=self._ok).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Cancel", width=100, command=self.cancel).pack(side="left", padx=6)
        self._list.bind("<<ListboxSelect>>", self._on_select)
        self._refresh()

    # --- recording ---------------------------------------------------------------

    def _toggle_recording(self) -> None:
        self._error.configure(text="")
        if self._recording:
            self._stop_recording()
            return
        self._recording = True
        self._events, self._down, self._pending_up = [], {}, {}
        self._steps = []
        self._record_button.configure(text="Stop")
        self._pad.configure(highlightbackground=ERROR_COLOR, highlightcolor=ERROR_COLOR)
        self._pad.focus_set()
        self._refresh()

    def _stop_recording(self) -> None:
        self._recording = False
        last = self._events[-1][0] if self._events else 0
        for name, kind in list(self._down.items()):  # never leave anything held
            self._events.append((last, f"{kind}_up", name))
        self._down.clear()
        self._rebuild_from_events()
        self._record_button.configure(text="Record")
        p = palette()
        self._pad.configure(highlightbackground=p["outline"], highlightcolor=p["outline"])
        self._refresh()

    def _record(self, time_ms: int, op: str, name: str) -> None:
        self._events.append((time_ms, op, name))
        self._rebuild_from_events()
        self._refresh()

    def _rebuild_from_events(self) -> None:
        self._steps = macros.steps_from_events(self._events, record_delays=self._timing.get())
        if len(self._steps) >= macros.MAX_STEPS and self._recording:
            self._stop_recording()
            self._error.configure(text=f"Recording stopped at {macros.MAX_STEPS} steps.")

    def _on_key(self, event) -> str:
        name = keys.name_from_tk(event.keysym, event.keycode, sys.platform == "win32")
        if not self._recording or name is None:
            return "break"
        if event.type == tk.EventType.KeyPress:
            if self._pending_up.get(name) == event.time:
                del self._pending_up[name]  # X11 auto-repeat sends release+press pairs: skip both
                return "break"
            if name in self._pending_up:  # a real release is still queued: record it first
                self._commit_release(name, self._pending_up[name])
            if name not in self._down:  # Windows auto-repeat repeats the press: ignore it
                self._down[name] = "key"
                self._record(event.time, "key_down", name)
        elif self._down.get(name) == "key":
            self._pending_up[name] = event.time
            self.after_idle(self._commit_release, name, event.time)
        return "break"

    def _commit_release(self, name: str, time_ms: int) -> None:
        if self._pending_up.get(name) != time_ms or not self.winfo_exists():
            return
        del self._pending_up[name]
        if self._recording and self._down.pop(name, None):
            self._record(time_ms, "key_up", name)

    def _on_mouse(self, event) -> str:
        self._pad.focus_set()
        button = self._MOUSE.get(event.num)
        if not self._recording or button is None:
            return "break"
        pressed = event.type == tk.EventType.ButtonPress
        if pressed and button not in self._down:
            self._down[button] = "button"
            self._record(event.time, "button_down", button)
        elif not pressed and self._down.pop(button, None):
            self._record(event.time, "button_up", button)
        return "break"

    # --- editing -----------------------------------------------------------------

    def _refresh(self, select: int | None = None) -> None:
        self._list.delete(0, "end")
        for i, step in enumerate(self._steps, 1):
            self._list.insert("end", f"{i}.  {macros.describe_step(step)}")
        if select is None and self._recording:
            select = len(self._steps) - 1
        if select is not None and 0 <= select < len(self._steps):
            self._list.selection_set(select)
            self._list.see(select)
        self._summary.configure(text=f"Steps: {macros.summary(self._steps)}")
        text = ("Recording: type keys, or click here with the left, middle or right mouse button"
                if self._recording else "Click Record to capture keys and mouse clicks here")
        self._pad.itemconfigure(self._pad_text, text=text)

    def _on_select(self, _event=None) -> None:
        index = self._index()
        if index is not None and self._steps[index]["op"] == "wait":
            self._delay.delete(0, "end")
            self._delay.insert(0, str(self._steps[index]["ms"]))

    def _index(self) -> int | None:
        selection = self._list.curselection()
        return selection[0] if selection else None

    def _insert(self, new_steps: list[dict]) -> None:
        if self._recording:
            return
        self._error.configure(text="")
        if len(self._steps) + len(new_steps) > macros.MAX_STEPS:
            self._error.configure(text=f"A macro has at most {macros.MAX_STEPS} steps.")
            return
        index = self._index()
        at = len(self._steps) if index is None else index + 1
        self._steps[at:at] = new_steps
        self._refresh(select=at + len(new_steps) - 1)

    def _add_key(self) -> None:
        if self._recording:
            return
        chord = KeyPickerDialog(self, self._engine).show()
        if chord:
            self._insert(macros.tap_steps(chord))

    def _add_click(self) -> None:
        self._insert(macros.click_steps(self._CLICKS[self._click.get()]))

    def _delay_ms(self) -> int | None:
        try:
            value = float(self._delay.get().replace(",", ".").strip())
        except ValueError:
            self._error.configure(text="Enter a delay in milliseconds, e.g. 100")
            return None
        return macros.wait_step(value)["ms"]

    def _add_delay(self) -> None:
        ms = self._delay_ms()
        if ms is not None:
            self._insert([macros.wait_step(ms)])

    def _set_delay(self) -> None:
        index, ms = self._index(), self._delay_ms()
        if self._recording or index is None or ms is None:
            return
        if self._steps[index]["op"] != "wait":
            self._error.configure(text="Select a Wait step first.")
            return
        self._steps[index] = macros.wait_step(ms)
        self._error.configure(text="")
        self._refresh(select=index)

    def _set_all_delays(self) -> None:
        ms = self._delay_ms()
        if ms is not None and not self._recording:
            self._steps = macros.set_all_delays(self._steps, ms)
            self._refresh()

    def _delete(self) -> None:
        index = self._index()
        if index is not None and not self._recording:
            del self._steps[index]
            self._refresh(select=min(index, len(self._steps) - 1))

    def _move(self, delta: int) -> None:
        index = self._index()
        if index is None or self._recording or not 0 <= index + delta < len(self._steps):
            return
        steps = self._steps
        steps[index], steps[index + delta] = steps[index + delta], steps[index]
        self._refresh(select=index + delta)

    def _clear(self) -> None:
        if not self._recording:
            self._steps = []
            self._refresh()

    def _ok(self) -> None:
        if self._recording:
            self._stop_recording()
        self.finish(macros.normalize_steps(self._steps))


class LayerDialog(ModalDialog):
    """Name and the one or two modifier controls of a layer; returns {"name", "modifiers"}."""

    NONE = "(nothing else)"

    def __init__(self, master, engine, title: str, name: str, modifiers: list[str],
                 taken: list[frozenset]) -> None:
        super().__init__(master, title, engine)
        self._taken = taken
        self._choices = {model.modifier_name(m): m for m in model.LAYER_MODIFIERS}
        labels = list(self._choices)
        ctk.CTkLabel(self, anchor="w", justify="left", wraplength=380, text=(
            "While the modifier is held, every control this layer overrides does something "
            "else (like the cross hotbar in FFXIV). The modifier keeps its own mapping; "
            "set it to No action for a pure modifier.")).pack(fill="x", padx=20, pady=(18, 8))
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=20)
        ctk.CTkLabel(grid, text="Hold", width=110, anchor="w").grid(row=0, column=0, sticky="w")
        self._first = ctk.CTkOptionMenu(grid, values=labels, width=240)
        self._first.grid(row=0, column=1, pady=3)
        ctk.CTkLabel(grid, text="and also", width=110, anchor="w").grid(row=1, column=0, sticky="w")
        self._second = ctk.CTkOptionMenu(grid, values=[self.NONE, *labels], width=240)
        self._second.grid(row=1, column=1, pady=3)
        ctk.CTkLabel(grid, text="Name", width=110, anchor="w").grid(row=2, column=0, sticky="w")
        self._layer_name = ctk.CTkEntry(grid, width=240, placeholder_text="e.g. Cross hotbar right")
        self._layer_name.grid(row=2, column=1, pady=3)
        names = {m: label for label, m in self._choices.items()}
        self._first.set(names[modifiers[0]] if modifiers else labels[0])
        self._second.set(names[modifiers[1]] if len(modifiers) > 1 else self.NONE)
        if name:
            self._layer_name.insert(0, name)
        self._error = ctk.CTkLabel(self, text="", text_color=ERROR_COLOR, anchor="w")
        self._error.pack(fill="x", padx=20, pady=(6, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(pady=(6, 18))
        ctk.CTkButton(buttons, text="OK", width=100, command=self._ok).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Cancel", width=100, command=self.cancel).pack(side="left", padx=6)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.cancel())

    def _ok(self) -> None:
        modifiers = [self._choices[self._first.get()]]
        second = self._second.get()
        if second != self.NONE:
            if self._choices[second] == modifiers[0]:
                self._error.configure(text="Pick two different controls, or nothing else.")
                return
            modifiers.append(self._choices[second])
        if frozenset(modifiers) in self._taken:
            self._error.configure(text="Another layer already uses these modifiers.")
            return
        name = model.clean_name(self._layer_name.get()) or model.default_layer_name(modifiers)
        self.finish({"name": name, "modifiers": modifiers})
