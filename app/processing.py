"""Pure signal processing for sticks, triggers and the D-pad.

Nothing here touches pygame or injects input, so the math is easy to reason
about and to test. Stick coordinates follow SDL: x grows to the right and y
grows downwards; values are in -1..1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.model import DIAGONALS, clamp

# Hysteresis margin for every analog breakpoint (fraction of full travel).
HYSTERESIS = 0.04
# Extra angle a stick must travel past a sector edge before the zone changes.
SECTOR_HYSTERESIS_DEG = 6.0
# Upper bound for the time-based mouse acceleration multiplier.
MAX_ACCEL_MULTIPLIER = 3.0

SECTORS_8 = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
SECTORS_4 = ("n", "e", "s", "w")


def schmitt(was_active: bool, value: float, threshold: float) -> bool:
    """Schmitt trigger: turn on at >= threshold, turn off only below threshold - margin.

    Edge case: analog values jittering around a breakpoint (worn triggers,
    noisy sticks) would otherwise toggle press/release on every poll and
    machine-gun the mapped key. The margin absorbs that noise.
    """
    margin = min(HYSTERESIS, threshold / 2)
    if was_active:
        return value >= threshold - margin
    return value >= threshold


class DriftFilter:
    """Anti-drift for one axis.

    Once |value| has stayed below the threshold for longer than the delay
    the axis is recentred to exactly 0, until it exceeds the threshold again.
    """

    __slots__ = ("below_since", "snapped")

    def __init__(self) -> None:
        self.below_since: float | None = None
        self.snapped = False

    def reset(self) -> None:
        self.below_since = None
        self.snapped = False

    def apply(self, value: float, threshold: float, delay_s: float, now: float) -> float:
        if threshold <= 0.0 or abs(value) >= threshold:
            self.reset()
            return value
        if self.below_since is None:
            self.below_since = now
        if self.snapped or now - self.below_since > delay_s:
            self.snapped = True
            return 0.0
        return value


def compass_angle(x: float, y: float) -> float:
    """0 deg = up, 90 deg = right (screen coordinates, y down)."""
    return math.degrees(math.atan2(x, -y)) % 360.0


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def sector_for(angle: float, zone_count: int, previous: str | None = None) -> str:
    """Directional zone for an angle, keeping the previous zone near sector edges."""
    names = SECTORS_8 if zone_count == 8 else SECTORS_4
    width = 360.0 / len(names)
    if previous in names:
        centre = names.index(previous) * width
        if _angle_diff(angle, centre) <= width / 2 + SECTOR_HYSTERESIS_DEG:
            return previous
    return names[int(((angle + width / 2) % 360.0) // width)]


def zones_for_sector(sector: str, diagonal_mode: str) -> tuple[str, ...]:
    """A diagonal emits its own zone ("combined") or both cardinals ("cardinals")."""
    if diagonal_mode == "cardinals" and sector in DIAGONALS:
        return DIAGONALS[sector]
    return (sector,)


def dpad_zones(up: bool, down: bool, left: bool, right: bool, diagonal_mode: str) -> tuple[str, ...]:
    x = int(right) - int(left)
    y = int(down) - int(up)
    if x == 0 and y == 0:
        return ()
    return zones_for_sector(sector_for(compass_angle(x, y), 8), diagonal_mode)


def accel_multiplier(accel: float, held_s: float) -> float:
    """Time-based mouse acceleration: +accel x speed per second held, capped."""
    return min(1.0 + max(accel, 0.0) * max(held_s, 0.0), MAX_ACCEL_MULTIPLIER)


# --- sticks ------------------------------------------------------------------

@dataclass(slots=True)
class StickResult:
    raw: tuple[float, float]          # as read from the device
    processed: tuple[float, float]    # unit direction x strength (0 inside the deadzone)
    unit: tuple[float, float]         # direction of travel
    magnitude: float                  # calibrated, drift-filtered radius (0..1)
    strength: float                   # 0 at the deadzone edge .. 1 at the outer threshold
    active: bool
    sector: str | None
    zones: frozenset
    outer: bool


class StickProcessor:
    """Per-device state for one stick: drift filters plus hysteresis memory."""

    def __init__(self) -> None:
        self.drift_x = DriftFilter()
        self.drift_y = DriftFilter()
        self.active = False
        self.sector: str | None = None
        self.outer = False

    def reset(self) -> None:
        self.__init__()

    def update(self, raw_x: float, raw_y: float, rest_x: float, rest_y: float, cfg: dict,
               drift_threshold: float, drift_delay_s: float, now: float) -> StickResult:
        x = clamp(raw_x - rest_x, -1.0, 1.0)
        y = clamp(raw_y - rest_y, -1.0, 1.0)
        x = self.drift_x.apply(x, drift_threshold, drift_delay_s, now)
        y = self.drift_y.apply(y, drift_threshold, drift_delay_s, now)
        magnitude = min(math.hypot(x, y), 1.0)  # square gates exceed 1 on diagonals
        deadzone = cfg["deadzone"]
        outer = max(cfg["outer"], deadzone + 0.01)

        self.active = magnitude > 1e-3 and schmitt(self.active, magnitude, deadzone)
        if not self.active:
            self.sector = None
            self.outer = False
            return StickResult((raw_x, raw_y), (0.0, 0.0), (0.0, 0.0), magnitude, 0.0,
                               False, None, frozenset(), False)

        unit = (x / magnitude, y / magnitude)
        strength = clamp((magnitude - deadzone) / (outer - deadzone), 0.0, 1.0)
        self.sector = sector_for(compass_angle(x, y), cfg["zone_count"], self.sector)
        self.outer = schmitt(self.outer, magnitude, outer)
        # Edge case: several zones of one stick can be active at once
        # ("cardinals" diagonals plus the outer ring). The engine diffs this
        # set against the previous one, so each zone presses and releases
        # independently and moving N -> NE -> E never re-presses N or E.
        zones: set[str] = set()
        if cfg["mode"] == "zones":
            zones.update(zones_for_sector(self.sector, cfg["diagonal_mode"]))
        if self.outer:
            zones.add("outer")
        return StickResult((raw_x, raw_y), (unit[0] * strength, unit[1] * strength), unit,
                           magnitude, strength, True, self.sector, frozenset(zones), self.outer)


# --- triggers ----------------------------------------------------------------

@dataclass(slots=True)
class TriggerResult:
    raw: float          # normalised 0..1 before drift filtering
    value: float        # after anti-drift
    processed: float    # response curve output between the two breakpoints
    zones: frozenset
    in_hysteresis: bool  # a zone is held only by the hysteresis margin


def normalize_trigger(raw: float, rest: float) -> float:
    span = 1.0 - rest
    if span <= 1e-6:
        return 0.0
    return clamp((raw - rest) / span, 0.0, 1.0)


def trigger_response(value: float, activation: float, full: float,
                     response: str, exponent: float) -> float:
    if value < activation:
        return 0.0
    if value >= full:
        return 1.0
    t = (value - activation) / (full - activation)
    return t ** exponent if response == "curved" else t


class TriggerProcessor:
    def __init__(self) -> None:
        self.drift = DriftFilter()
        self.soft = False
        self.full = False

    def reset(self) -> None:
        self.__init__()

    def update(self, raw: float, rest: float, cfg: dict, drift_threshold: float,
               drift_delay_s: float, now: float) -> TriggerResult:
        normalized = normalize_trigger(raw, rest)
        value = self.drift.apply(normalized, drift_threshold, drift_delay_s, now)
        self.soft = schmitt(self.soft, value, cfg["activation"])
        self.full = schmitt(self.full, value, cfg["full"])
        processed = trigger_response(value, cfg["activation"], cfg["full"],
                                     cfg["response"], cfg["curve_exponent"])
        zones = frozenset(z for z, on in (("soft", self.soft), ("full", self.full)) if on)
        in_hysteresis = (self.soft and value < cfg["activation"]) or (self.full and value < cfg["full"])
        return TriggerResult(normalized, value, processed, zones, in_hysteresis)
