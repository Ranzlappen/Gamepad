# Changelog

All notable changes to **Gamepad Mapper** are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Pytest suite (engine, processing, model, storage, injector, runtime) with an 80 % coverage gate.
- CI (ruff + pytest on Linux and Windows), CodeQL, gitleaks, OpenSSF Scorecard, dependency review
  and Dependabot.
- Community files: Code of Conduct, Contributing, Security policy, CODEOWNERS, PR and issue templates.
- `.standards-version`, `.editorconfig`, pre-commit configuration, `pyproject.toml` tooling config.

## [1.0.0] - 2026-10-08

### Added
- Initial release: gamepad-to-keyboard/mouse mapping engine, visual mapping UI, calibration and
  anti-drift, three default profiles, system-tray icon and settings.

[Unreleased]: https://github.com/Ranzlappen/Gamepad/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Ranzlappen/Gamepad/releases/tag/v1.0.0
