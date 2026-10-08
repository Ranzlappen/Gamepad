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
in order, resync with polled state, process sticks/triggers (`app/processing.py`), drive slot
state machines (`MappingEngine._drive`) → release due taps → one relative mouse move.

## Build & Development

```
pip install -r requirements.txt   # the only five runtime dependencies
python main.py                    # run with a console for warnings
pythonw main.py                   # run without a console (what the Run key uses)
```

Windows 10/11, Python 3.11+ (high-resolution `time.sleep`). The pure modules (`model`,
`processing`, `layouts`, `keys`, `profiles`, `settings`) import nothing platform-specific and can
be exercised on any OS; `engine` accepts injected `injector_factory` / `device_manager_factory`
for headless checks.

## Key Conventions

* **Dependencies are fixed**: pygame, pynput, pystray, Pillow, customtkinter. Use the stdlib
  (`ctypes`, `winreg`) for anything else; do not add packages.
* **Never steal focus.** The engine creates no windows; the UI only lifts or focuses itself after
  an explicit user action (tray Show, a dialog the user opened).
* **Injection pauses only for keyboard-capturing modal dialogs.** Use `ModalDialog` subclasses or
  `injection_paused(engine)` around native dialogs. Minimised or unfocused must keep injecting.
* **Every held key has an owner** `(instance_id, slot_id)` or `("tap", n)`. Always release through
  `Injector.release_keys/release_button/release_owners/release_all`; never call the backend
  directly. Profile swaps, pauses, layout changes, disconnects and exit release everything first.
* **Profiles are human-readable JSON** in `profiles/`, validated by `model.normalize_profile`
  (unknown or invalid fields fall back to defaults). Bump `SCHEMA_VERSION` and add a migration in
  `normalize_profile` if the shape changes. Slot ids look like `button:a`, `dpad:ne`,
  `stick:left:outer`, `trigger:rt:soft`.
* **Templates live in code** (`app/defaults.py`). The tracked `profiles/*.json` defaults must equal
  `json.dumps(defaults.template(name), indent=2, ensure_ascii=False) + "\n"`; regenerate them
  after changing a template.
* **Controller layouts are per GUID** in `settings.json` (`layouts`), separate from profiles.
  Calibration offsets are per GUID inside the active profile (`calibration`).
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

No automated test suite is committed (scope of the initial build). Validate changes with:

* **Headless logic check**: drive `MappingEngine._tick` with a fake device manager and a fake
  injector backend (see the constructor factories) for zones, taps, hold thresholds, pauses,
  profile swaps and disconnects.
* **Manual smoke checklist** on Windows with a real controller:
  1. Hot-plug: connect and disconnect while a mapped key is held; the key must release.
  2. Each default profile: WASD diagonals, mouse look, triggers, D-pad, bumpers.
  3. Hold threshold: short tap vs long press on one button.
  4. Calibrate, then confirm mappings are unchanged and drift is recentred.
  5. Minimise and focus another app (e.g. Notepad); input must keep arriving.
  6. Open the key-capture dialog while holding a mapped button; nothing leaks into it.
  7. Tray: Show/Hide, Pause/Resume (icon changes), profile switch, Exit releases keys.

## Security & Secrets

* **Threat model**: a local, single-user desktop tool. It injects input into whatever window has
  focus, so it must never inject when the user did not map a control. There is no network access.
* **Secrets**: none. Imported profiles are untrusted JSON and are always passed through
  `model.normalize_profile`; they can only express key, mouse-button and mouse-move actions.
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
