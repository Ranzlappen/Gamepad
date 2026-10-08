# Changelog

All notable changes to **Gamepad Mapper** are recorded here. The project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

New entries are written by [release-please](https://github.com/googleapis/release-please) from the
Conventional Commit titles of merged PRs (see `.github/workflows/release-please.yml`; it runs once
the `RELEASE_PLEASE_ENABLED` repository variable is `true`). Do not edit entries by hand.

## 1.0.0 (2026-10-08)

### Features

* Gamepad-to-keyboard/mouse mapping engine: hot-plug for up to 4 controllers, 250 Hz background
  polling, press/release/tap actions with hold thresholds, stick zones with combined or cardinal
  diagonals, mouse look, trigger breakpoints with curves, calibration and anti-drift.
* Visual mapping UI with live raw-vs-processed previews, input-layout detection, three default
  profiles (Desktop / Mouse, FPS Standard, Empty), profile import/export, system-tray icon and
  settings.
