# Gamepad Mapper

[![CI](https://github.com/Ranzlappen/Gamepad/actions/workflows/ci.yml/badge.svg)](https://github.com/Ranzlappen/Gamepad/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Standards](https://img.shields.io/badge/repo--standards-v3-informational)](https://github.com/Ranzlappen/repo-standards)

A standalone Windows app that turns gamepad input into keyboard keys and mouse actions, in the spirit of Xpadder.

> **New here?** If you just want to use the app, jump to [Getting Started](#getting-started).
> If you want to change the code, see [Developer Setup](#developer-setup) and [`CLAUDE.md`](./CLAUDE.md).

---

## What this is

Gamepad Mapper lets you play keyboard-and-mouse games with a controller, or drive your desktop
from the couch. Every control is mapped on its own: face buttons, bumpers, stick clicks, all eight
D-pad directions, both sticks (eight zones, an outer ring, or continuous mouse movement) and both
triggers (an activation point and a full-press point). A mapping can press a key or key chord
(held or tapped), click a mouse button, or move the mouse, and can fire on press, on release, or
both, with a separate action for short taps. It runs in the background from the system tray and
keeps working while the window is minimised or another app has focus.

---

## Quick Reference

| I want to... | Do this |
| --- | --- |
| Start the app | Double-click `main.py` (or run `pythonw main.py`) |
| Map a button | **Mapping** tab, click the button on the controller picture, choose an action under **On press** |
| Map a key combination | Type it as `ctrl+shift+s` or click **Capture...** and press it |
| Make a stick move the mouse | Click the stick, set **Mode** to **Mouse**, tune speed, curve and acceleration |
| Give a button a tap action and a hold action | Set **Hold threshold** (e.g. 250 ms) and fill in **Short tap** |
| Fix stick drift | Controllers tab: **Calibrate selected controller**, then adjust **Anti-drift deadzone** |
| Fix a button that lands on the wrong control | Controllers tab: **Detect** next to that control and press it |
| Switch, copy or share profiles | Use the profile bar at the top (New, Duplicate, Rename, Delete, Import, Export) |
| Pause all mapping | **Pause mapping** button, or the tray menu |
| Run the tests and lint | `pip install -r requirements-dev.txt`, then `ruff check .` and `python -m pytest --cov` |
| Download a release | [Releases](https://github.com/Ranzlappen/Gamepad/releases): `GamepadMapper-vX.Y.Z.zip` (verify with `gh attestation verify`) |
| Quit completely | Tray icon, **Exit** (the window close button only hides to the tray by default) |

---

## Getting Started

1. Install **Python 3.11 or newer** (64-bit) from [python.org](https://www.python.org/downloads/windows/).
   Tick "Add python.exe to PATH" during setup.
2. Download this repository (green **Code** button, **Download ZIP**) and unzip it.
3. Open a terminal in the unzipped folder and install the dependencies once:
   ```
   py -m pip install -r requirements.txt
   ```
4. Start the app by double-clicking `main.py`, or run `pythonw main.py` to start it without a
   console window.
5. Plug in a controller. It shows up within half a second; up to four controllers are used at once.
6. Pick a profile (**Desktop / Mouse**, **FPS Standard** or **Empty**) and start playing.

The three default profiles are created on first run and are always available as templates under
**New**.

---

## Developer Setup

### Prerequisites

* Windows 10 or 11 and Python 3.11+ (64-bit). Check with `py --version`.
  Python 3.11+ is needed for the high-resolution `time.sleep` the mapping loop relies on.
* A game controller for manual testing (Xbox-style, PlayStation, Switch Pro, or any DirectInput pad).

### Install and run

```
py -m venv .venv                       # optional virtual environment
.venv\Scripts\activate
pip install -r requirements.txt        # pygame, pynput, pystray, Pillow, customtkinter
python main.py                         # run with a console (shows warnings)

pip install -r requirements-dev.txt    # pytest, pytest-cov, ruff
ruff check .                           # lint
python -m pytest --cov                 # tests (80 % coverage gate, also run on Linux)
```

### Modules

| Module | Path | Role |
| --- | --- | --- |
| Entry point | `main.py` | Single-instance guard, SDL environment, starts the UI |
| Mapping engine | `app/engine.py` | Background poll-and-inject loop, slot state machines, calibration |
| Gamepad polling | `app/gamepad.py` | pygame device enumeration, hot-plug, raw reads |
| Signal processing | `app/processing.py` | Deadzones, zones, hysteresis, anti-drift, trigger curves |
| Input layouts | `app/layouts.py` | Raw button/axis/hat to logical control bindings |
| Output | `app/injector.py` | pynput key/button injection with per-owner bookkeeping |
| Profiles | `app/model.py`, `app/defaults.py`, `app/profiles.py` | Schema, templates, JSON storage |
| Settings | `app/settings.py` | `settings.json` and the Windows Run key |
| Tray | `app/tray.py` | pystray icon and menu |
| UI | `app/ui/` | customtkinter window, controller view, editors, dialogs |

### CI/CD at a glance

| Workflow | Trigger | What it does |
| --- | --- | --- |
| [`ci.yml`](./.github/workflows/ci.yml) | PR, push to `main` | ruff + pytest with coverage on Linux and Windows, Python 3.11 and 3.13 |
| [`security-scan.yml`](./.github/workflows/security-scan.yml) | PR, push, weekly | CodeQL (Python), gitleaks, OpenSSF Scorecard (public repos) |
| [`dependency-review.yml`](./.github/workflows/dependency-review.yml) | PR | Fails on high-severity dependency vulnerabilities |
| [`repo-checks.yml`](./.github/workflows/repo-checks.yml) | PR, push to `main` | actionlint, offline Markdown link check, action SHA-pin lint |
| [`release-please.yml`](./.github/workflows/release-please.yml) | push to `main` (opt-in) | Release PRs from Conventional Commits; attaches a signed-provenance zip to each Release |

Dependabot ([`dependabot.yml`](./.github/dependabot.yml)) opens weekly grouped updates for pip and GitHub Actions.
Branch protection and release policy live in [`.github/GOVERNANCE.md`](./.github/GOVERNANCE.md).

### Architecture source of truth

[`CLAUDE.md`](./CLAUDE.md) is the authoritative architecture doc (threading model, conventions,
data files). When this README and `CLAUDE.md` disagree, `CLAUDE.md` wins and this README needs
updating.

### AI tooling

Tool-specific entrypoints ([`.cursorrules`](./.cursorrules), and `.github/copilot-instructions.md`
if added) defer to [`CLAUDE.md`](./CLAUDE.md). [`ai/AI_TEAM_PLAYBOOK.md`](./ai/AI_TEAM_PLAYBOOK.md)
covers how several AI tools share the repo.

### Operating modes and behavior preservation

Changes follow [`repo-standards`](https://github.com/Ranzlappen/repo-standards): one focused
branch and PR per task (standards upgrades start with Phase 0 migration planning), 100 % of
existing behavior kept unless a change says otherwise, and a **Repo-specific risks /
edge-cases** section in every PR description. Out-of-scope findings are filed as issues labelled
`out-of-scope,from-claude`; set the repository variable `DISABLE_OUT_OF_SCOPE_ISSUES=true` to keep
them in PR descriptions instead.

---

## How to map controls

**Buttons and D-pad.** Each slot has an **On press** action, an optional **Hold threshold**, a
**Short tap** action (fires when you release before the threshold) and an **On release** action.
Keys can be **Hold** (down while the control is held) or **Tap** (a short press). Example: X with
`On press = r (Hold)`, `Hold threshold = 300 ms`, `Short tap = e` sends `e` on a quick tap and
holds `r` on a long press.

**Sticks.** In **Directional zones** mode a stick has eight zones (or four) plus an **Outer** ring
that fires past the outer threshold (handy for sprint). **Diagonals** decides whether up-right fires
its own zone or both Up and Right together (the WASD setup). In **Mouse** mode the stick moves the
pointer continuously; speed is reached at the outer threshold, **Response curve** above 1 gives
finer aim near the centre, and **Acceleration** ramps the speed while the stick is held at the edge.
The live preview shows the raw position (grey) against the processed output (blue).

**Triggers.** **Activation threshold** and **Full-press threshold** are two separate breakpoints
with their own mappings, and the response between them can be linear or curved. A 4 % hysteresis
band stops a trigger resting near a breakpoint from flickering.

**Calibration and drift.** With the sticks centred and triggers released, **Calibrate** samples the
resting position for two seconds and stores per-axis offsets in the active profile. Afterwards, an
axis that stays below the anti-drift deadzone (default 8 %) for more than 300 ms is snapped to zero.
Recalibrating never touches your mappings.

---

## Project Structure

```
Gamepad/
├── main.py                ← entry point (run this)
├── app/
│   ├── engine.py          ← background mapping loop
│   ├── gamepad.py         ← pygame polling and hot-plug
│   ├── processing.py      ← stick / trigger math
│   ├── layouts.py         ← raw input → logical control bindings
│   ├── injector.py        ← keyboard / mouse output
│   ├── model.py           ← profile schema and validation
│   ├── defaults.py        ← the three template profiles
│   ├── profiles.py        ← profile files (create, rename, import, export)
│   ├── settings.py        ← settings.json and start-with-Windows
│   ├── tray.py            ← system-tray icon
│   └── ui/                ← customtkinter window, editors and dialogs
├── tests/                 ← pytest suite (fake controller and output backend)
├── profiles/              ← one JSON file per profile (defaults are tracked)
├── .github/               ← CI, security scans, Dependabot, community files
├── requirements.txt       ← the five runtime dependencies
├── requirements-dev.txt   ← pytest, pytest-cov, ruff
├── pyproject.toml         ← ruff, pytest and coverage configuration
├── ai/                    ← multi-AI-tool coordination playbook
├── CHANGELOG.md           ← release notes (written by release-please)
├── CLAUDE.md              ← architecture source of truth
└── README.md              ← this file
```

**For everyday use** you only touch:

* `profiles/` to back up, share or hand-edit profiles (plain, human-readable JSON).
* `settings.json` (created next to `main.py` on first run) for preferences and controller layouts.

Debug logs (when enabled in **Settings**) go to `%APPDATA%\GamepadMapper\logs`.

**For deeper changes** see [`CLAUDE.md`](./CLAUDE.md).

---

## Known limitations

* Input is injected with `SendInput` (through pynput). Games protected by anti-cheat, or apps
  running as administrator while Gamepad Mapper is not, may ignore it. Run both at the same
  privilege level.
* All connected controllers share the active profile; calibration is stored per controller model
  (GUID) inside that profile.
* Controllers are read through SDL's raw joystick API. Auto-detect uses SDL's own mapping for
  every controller SDL knows (Xbox, PlayStation, Switch Pro and most others); a pad SDL does not
  know may need a few **Detect** clicks once (Controllers tab).

## Community standards

Contributions are governed by the
[GitHub Community Guidelines](https://docs.github.com/en/site-policy/github-terms/github-community-guidelines),
the [GitHub Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies),
and this repo's [`CODE_OF_CONDUCT.md`](./.github/CODE_OF_CONDUCT.md). See
[`.github/CONTRIBUTING.md`](./.github/CONTRIBUTING.md) for the contributor guide and
[`.github/SECURITY.md`](./.github/SECURITY.md) for private vulnerability reporting.

## License

This project is released under the **MIT License**. The full text is in [`LICENSE`](./LICENSE) at
the repo root; that file is the authoritative copy and this section is only a summary.

Copyright (c) 2026 Ranzlappen.

In short: do whatever you want with this code as long as you keep the copyright notice. No warranty.
