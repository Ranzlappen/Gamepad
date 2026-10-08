# Gamepad Mapper

Standalone Windows desktop app (Python) that maps gamepad input to keyboard keys and mouse
actions, Xpadder-style. Runs locally from `main.py`; there is no server, build step or deployment.

## Architecture

Three threads, strictly separated:

* **Tk main thread** (`app/ui/`) owns every widget. It never touches pygame or pynput.
* **Mapping engine thread** (`app/engine.py`) owns pygame (`app/gamepad.py`) and the injector
  (`app/injector.py`). SDL pumps the Windows message queue of the thread that initialised it,
  so pygame init, pump, reads and `pygame.quit()` must all stay on this thread.
* **Tray thread** (`app/tray.py`) runs pystray's message loop. Its menu callbacks only post work.

`main.py` sets the SDL environment before pygame loads: background joystick events on, and the
screensaver allowed (SDL's video init would otherwise keep the display awake).

Communication:

* UI → engine: thread-safe methods on `MappingEngine` (`set_profile`, `set_layouts`,
  `pause`/`resume`, `set_user_paused`, `request_calibration`, ...). `set_profile` is latest-wins.
* Engine → UI: `snapshot()` returns an immutable dict published at about 60 Hz; the UI polls it
  every 33 ms. Calibration results arrive through `on_calibrated`, which posts to the UI queue.
* Tray/engine → Tk: `MainWindow.post(fn, *args)` queues work that `_drain_queue` runs on Tk.

Per tick (default 250 Hz, `Settings.polling_hz`): drain commands → apply a pending profile →
`DeviceManager.poll()` (events + 500 ms hot-plug rescan) → per device: replay button/hat events
in order, resync with polled state, process sticks/triggers (`app/processing.py`), pick the
active layer, drive slot state machines (`MappingEngine._drive`) → advance running macros →
release due taps → one relative mouse move.

## Build & Development

```
pip install -r requirements.txt   # the only five runtime dependencies
pip install -r requirements-dev.txt  # + pytest, pytest-cov, ruff (CI uses this)
ruff check .                      # lint (config in pyproject.toml)
python -m pytest --cov            # tests; fails under 80 % coverage
python main.py                    # run with a console for warnings
pythonw main.py                   # run without a console (what the Run key uses)
```

Windows 10/11, Python 3.11+ (high-resolution `time.sleep`). The pure modules (`model`, `macros`,
`processing`, `layouts`, `keys`, `profiles`, `settings`) import nothing platform-specific and can
be exercised on any OS; `engine` accepts injected `injector_factory` / `device_manager_factory`
for headless checks.

## Key Conventions

* **Runtime dependencies are fixed**: pygame, pynput, pystray, Pillow, customtkinter. Use the
  stdlib (`ctypes`, `winreg`) for anything else. Dev tools (pytest, ruff) live in
  `requirements-dev.txt` only.
* **Never steal focus.** The engine creates no windows; the UI only lifts or focuses itself after
  an explicit user action (tray Show, a dialog the user opened).
* **Injection pauses only for keyboard-capturing modal dialogs.** Use `ModalDialog` subclasses or
  `injection_paused(engine)` around native dialogs. Minimised or unfocused must keep injecting.
* **Every held key has an owner** `(instance_id, slot_id)`, `(instance_id, "macro:<n>")` or
  `("tap", n)`. Always release through `Injector.release_keys/release_button/release_owners/
  release_all`; never call the backend directly. Profile swaps, pauses, layout changes,
  disconnects and exit release everything first (and stop running macros).
* **Profiles are human-readable JSON** in `profiles/`, validated by `model.normalize_profile`
  (unknown or invalid fields fall back to defaults). Bump `SCHEMA_VERSION` and add a migration in
  `normalize_profile` if the shape changes (2 added paddles `p1`-`p4`, macro actions and
  `layers`). Slot ids look like `button:a`, `button:p1`, `dpad:ne`, `stick:left:outer`,
  `trigger:rt:soft`.
* **Layers** (`profile["layers"]`, max 8): 1-2 modifiers (`button:<b>` / `trigger:<t>`) and
  per-slot overrides; the most specific held layer wins and a modifier's own slots never take
  overrides. **Macros** (`app/macros.py`) are validated step lists run by the engine per tick.
* **Templates live in code** (`app/defaults.py`). The tracked `profiles/*.json` defaults must equal
  `json.dumps(defaults.template(name), indent=2, ensure_ascii=False) + "\n"`; regenerate them
  after changing a template (`tests/test_model_keys_layouts.py` fails when they drift).
* **Controller layouts are per GUID** in `settings.json` (`layouts`), separate from profiles.
  "Auto" uses SDL's own game-controller mapping (`gamepad._sdl_mapping`, read on the engine
  thread at connect; raw axis order differs per SDL driver) and fills gaps from a preset; manual
  presets and Detect overrides win. Calibration offsets are per GUID in the active profile.
* **UI edits mutate `MainWindow.profile` in place**, then call `profile_changed()` (engine update
  now, debounced save). Call `_flush_edits()` before switching the edited target.

## Edge cases (keep the comments in code)

| Case | Where |
| --- | --- |
| Disconnect while keys are held: release everything that device owns | `MappingEngine._on_device_removed` |
| Several zones of one stick active at once (cardinals + outer) | `StickProcessor.update`, set diff in `_drive` |
| Trigger/stick jitter around a breakpoint: 4 % Schmitt hysteresis | `processing.schmitt`, `SECTOR_HYSTERESIS_DEG` |
| Windows key repeat vs synthetic keys: one key-down per hold, refcounted owners | `Injector._press` |
| Rapid profile switches: latest-wins, release-all before apply | `MappingEngine._apply_pending_profile` |
| Press and release between two polls | button/hat events replayed in `_process_device` |
| Taps: 30 ms minimum down time, re-triggered on fast repeats | `TAP_DURATION_S`, `Injector._press(retrigger)` |
| Modifier pressed/released while a control is held: slot latched at its press | `MappingEngine._drive` |
| Macro re-triggered while running (ignored); keys it leaves down are released | `_start_macro`, `_end_macro` |

With **Debug logging** on, these events go to `%APPDATA%\GamepadMapper\logs\gamepad-mapper.log`
(1 MB x 3, rotating). Use `debug_throttled` for anything that can fire every tick.

## Data files

| File | Written by | Tracked |
| --- | --- | --- |
| `settings.json` (beside `main.py`) | `Settings.save` | No (gitignored) |
| `profiles/desktop-mouse.json`, `fps-standard.json`, `empty.json` | first run / templates | Yes |
| other `profiles/*.json` | the user | No (gitignored) |
| `%APPDATA%\GamepadMapper\logs\*` | debug logging | No |

All JSON writes go through `paths.atomic_write_text` (temp file + `os.replace`).

## Testing

`python -m pytest --cov` (80 % gate over `app/`, excluding `app/ui/` and `app/tray.py`).
`tests/conftest.py` provides `Rig`: the real `MappingEngine` driven by manual `tick()` calls with
a `FakeDeviceManager` and a `FakeBackend`, so zones, taps, hold thresholds, pauses, profile swaps,
disconnects and calibration are deterministic and need no hardware or display. Add an engine
test for every edge case in the table above. The UI and tray have no automated tests; run the
manual smoke checklist in [`.github/CONTRIBUTING.md`](./.github/CONTRIBUTING.md) on Windows with a
real controller.

## Deployment & CI/CD

| Workflow | Trigger | Deploys |
| --- | --- | --- |
| `ci.yml` | PR, push to `main` | Nothing (ruff + pytest on ubuntu/windows, Python 3.11 and 3.13) |
| `security-scan.yml` | PR, push, weekly | Nothing (CodeQL, gitleaks, Scorecard on public repos) |
| `dependency-review.yml` | PR | Nothing (fails on high-severity CVEs) |
| `repo-checks.yml` | PR, push to `main` | Nothing (actionlint, offline link check, SHA-pin lint) |
| `release-please.yml` | push to `main` (gated) | Release PR; on merge a `vX.Y.Z` Release with an attested zip |

No secrets. Actions are SHA-pinned with exact-version comments; jobs set `timeout-minutes`;
workflow permissions are `contents: read`. Required checks have no path filters (a skipped
required check blocks merging). release-please (variable `RELEASE_PLEASE_ENABLED=true`) owns
`CHANGELOG.md`, the manifest and the `x-release-please-version` line, so PR titles must be
Conventional Commits. `.gitattributes` `export-ignore` keeps tests and tooling out of release
zips. Branch protection: [`.github/GOVERNANCE.md`](./.github/GOVERNANCE.md).

## Security & Secrets

* **Threat model**: a local, single-user desktop tool. It injects input into whatever window has
  focus, so it must never inject when the user did not map a control. There is no network access.
* **Secrets**: none. Imported profiles are untrusted JSON and are always passed through
  `model.normalize_profile`; they can only express key, mouse-button and mouse-move actions,
  and macros made of key/mouse-button steps and waits (capped at 500 steps, 10 s per wait).
* **Registry**: only `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\GamepadMapper`, and only
  when the user enables "Start with Windows".

## Tech Stack

| Layer | Technology | Role | Why |
| --- | --- | --- | --- |
| Runtime | Python 3.11+ | App | High-resolution sleep on Windows |
| Input | pygame 2 (SDL2 joystick API) | Polling, hot-plug | XInput, HIDAPI, DirectInput coverage |
| Output | pynput + `SendInput` via ctypes | Keys, buttons, relative mouse | Raw-input games need relative motion |
| UI | customtkinter | Window, editors | Modern Tk widgets, light/dark |
| Tray | pystray + Pillow | Tray icon/menu | Runs on its own thread |

## Working rules for AI contributors

* **Behavior preservation (non-negotiable)**: per `repo-standards` PROMPT.md rule 2, keep 100 % of
  existing functionality unless the task says otherwise, read the affected code paths before
  editing, and include **Repo-specific risks / edge-cases** in every PR description.
* **AI readiness**: this file → `README.md` → [`.cursorrules`](./.cursorrules); this file wins on
  disagreement. Multi-tool rules: [`ai/AI_TEAM_PLAYBOOK.md`](./ai/AI_TEAM_PLAYBOOK.md).
* **Standards upgrades** run `repo-standards` Phase 0 (migration planning) first; the version this
  repo follows is in `.standards-version`.
* **Out-of-scope findings (opt-out)**: file an issue labelled `out-of-scope,from-claude` and link it
  from the PR; with the repo variable `DISABLE_OUT_OF_SCOPE_ISSUES=true`, list them in the PR only.
* **Operating mode**: one focused branch and PR per task by default; open it only after the
  maintainer agrees. Never add commits to a branch whose PR already merged: cut a new branch
  from `origin/main`.
* **Plan hygiene**: when a plan is reopened, start a fresh plan or prune finished sections.

## Post-task self-check

After every turn that changes code, scan for things that should be codified in `README.md`, this
file, or `requirements.txt`: new settings keys, profile schema changes, new dependencies (not
allowed without discussion), new data files, changed edge-case handling. Always include a
**Repo-specific risks / edge-cases** note: does the change keep all pygame calls on the engine
thread, release every synthetic key on swap/pause/disconnect/exit, keep profiles valid under
`normalize_profile`, and keep the tracked default profiles in sync with `app/defaults.py`?
"None observed" is acceptable; the note must be present.

* **Auto-implement** small, unambiguous doc updates (new setting → README Quick Reference row).
* **Ask first** for anything structural (threading model, profile schema, new top-level file).
