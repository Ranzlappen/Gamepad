"""Shared UI helpers: theme palette, bounded number fields and zone pickers."""

from __future__ import annotations

from collections.abc import Callable

import customtkinter as ctk

from app.model import clamp


def palette() -> dict[str, str]:
    """Canvas colours for the current light/dark appearance."""
    dark = ctk.get_appearance_mode() == "Dark"
    return {
        "panel": "#2b2b2b" if dark else "#dbdbdb",
        "body": "#3b4250" if dark else "#c9ced6",
        "control": "#4f5869" if dark else "#eef0f3",
        "outline": "#6b7486" if dark else "#8b94a3",
        "text": "#e8eaed" if dark else "#1f2329",
        "muted": "#9aa1ad" if dark else "#59606b",
        "mapped": "#5dade2" if dark else "#1f6aa5",
        "pressed": "#2ecc71",
        "selected": "#f39c12",
        "raw": "#9aa1ad" if dark else "#6b7486",
        "processed": "#3b8ed0",
        "zone": "#27ae60",
        "grid": "#454c59" if dark else "#b5bcc7",
    }


class NumberField(ctk.CTkFrame):
    """Label + entry for a bounded number; commits on Enter or focus loss.

    Percent fields display 0-100 and store 0-1.
    """

    def __init__(self, master, label: str, getter: Callable[[], float],
                 setter: Callable[[float], None], lo: float, hi: float, *,
                 percent: bool = False, decimals: int = 0, unit: str = "",
                 width: int = 64, label_width: int = 150) -> None:
        super().__init__(master, fg_color="transparent")
        self._getter, self._setter = getter, setter
        self._lo, self._hi, self._percent, self._decimals = lo, hi, percent, decimals
        ctk.CTkLabel(self, text=label, width=label_width, anchor="w").pack(side="left")
        self._var = ctk.StringVar()
        self.entry = ctk.CTkEntry(self, width=width, textvariable=self._var)
        self.entry.pack(side="left")
        suffix = "%" if percent else unit
        if suffix:
            ctk.CTkLabel(self, text=suffix, width=28, anchor="w").pack(side="left", padx=(4, 0))
        self.entry.bind("<Return>", self._commit)
        self.entry.bind("<FocusOut>", self._commit)
        self.refresh()

    def refresh(self) -> None:
        value = self._getter()
        shown = value * 100 if self._percent else value
        self._var.set(f"{shown:.{self._decimals}f}")

    def set_enabled(self, enabled: bool) -> None:
        self.entry.configure(state="normal" if enabled else "disabled")

    def _commit(self, _event=None) -> None:
        try:
            value = float(self._var.get().replace(",", ".").replace("%", "").strip())
        except ValueError:
            self.refresh()
            return
        if self._percent:
            value /= 100
        value = clamp(value, self._lo, self._hi)
        if abs(value - self._getter()) > 1e-9:
            self._setter(value)
        self.refresh()


class ZonePicker(ctk.CTkFrame):
    """A grid of zone buttons; the selected zone is highlighted, mapped zones marked."""

    def __init__(self, master, grid: list[list[str | None]], labels: dict[str, str],
                 on_select: Callable[[str], None], cell_width: int = 64) -> None:
        super().__init__(master, fg_color="transparent")
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._labels = labels
        self._on_select = on_select
        self._selected: str | None = None
        for r, row in enumerate(grid):
            for c, zone in enumerate(row):
                if zone is None:
                    continue
                button = ctk.CTkButton(self, text=labels[zone], width=cell_width, height=30,
                                       command=lambda z=zone: self._on_select(z))
                button.grid(row=r, column=c, padx=2, pady=2)
                self._buttons[zone] = button
        self._default_fg = self._buttons[next(iter(self._buttons))].cget("fg_color")

    def update_state(self, selected: str, mapped: set[str], enabled: set[str]) -> None:
        self._selected = selected
        for zone, button in self._buttons.items():
            text = self._labels[zone] + (" •" if zone in mapped else "")
            button.configure(
                text=text,
                fg_color="#d35400" if zone == selected else self._default_fg,
                state="normal" if zone in enabled else "disabled",
            )


def section(master, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text, font=ctk.CTkFont(size=14, weight="bold"), anchor="w")
