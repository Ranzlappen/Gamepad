# Contributing to Gamepad Mapper

Anything not covered here lives in [`CLAUDE.md`](../CLAUDE.md) (architecture, conventions, data
files) or the [`README.md`](../README.md) (user-facing docs).

## Quick links

- [Open issues](https://github.com/Ranzlappen/Gamepad/issues) and [pull requests](https://github.com/Ranzlappen/Gamepad/pulls)
- [Code of Conduct](./CODE_OF_CONDUCT.md)
- [Security policy](./SECURITY.md)

## Setup

```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
ruff check .
python -m pytest --cov
```

Windows 10/11 and Python 3.11+ are needed to run the app. The tests and lint also run on Linux
because the mapping logic is tested against a fake controller and a fake output backend.

## How to propose a change

1. **Open an issue first** for anything beyond a small fix.
2. **Branch from `main`**: `fix/stuck-key-on-pause`, `feat/per-controller-profiles`.
3. **Keep PRs small**: one focused change per PR.
4. **Add or update tests** for engine, processing, model or storage changes.
5. **Update docs in the same PR** when behavior, settings or profile fields change. If a profile
   template in `app/defaults.py` changes, regenerate `profiles/*.json` (see `CLAUDE.md`).
6. **No new runtime dependencies.** The five in `requirements.txt` are fixed.

## Conventional commits

This project uses [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
`feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `perf`, `style`, `revert`, with an
optional scope (`feat(engine): ...`). Breaking changes get `!` and a `BREAKING CHANGE:` footer.
Install the local hooks once with `pip install pre-commit && pre-commit install`.

## Manual smoke checklist (Windows, real controller)

The UI and tray have no automated tests. Before merging UI, tray or device changes:

1. Hot-plug: connect and disconnect while a mapped key is held; the key must release.
2. Each default profile: WASD diagonals, mouse look, triggers, D-pad, bumpers.
3. Hold threshold: short tap vs long press on one button.
4. Calibrate, then confirm mappings are unchanged and drift is recentred.
5. Minimise and focus another app (e.g. Notepad); input must keep arriving.
6. Open the key-capture dialog while holding a mapped button; nothing leaks into it.
7. Tray: Show/Hide, Pause/Resume (icon changes), profile switch, Exit releases keys.
8. Key list (**List...**): the mouse wheel scrolls it, search finds keys, the chosen key sticks.
9. Macros: record keys and clicks, play one back once and on repeat; release mid-macro,
   unplug mid-macro and pause mid-macro must leave nothing held.
10. Layers: add an RT layer, map X in it; X alone and RT+X differ, a modifier released
    while X is held keeps X's key until X is released.
11. Back paddles (if your pad has them): each one lights up and fires its own mapping.

## Pull request checklist

- [ ] CI is green (ruff, pytest with the 80 % coverage gate, on Linux and Windows).
- [ ] Held synthetic keys are still released on pause, profile switch, disconnect and exit.
- [ ] Docs updated where relevant.
- [ ] No secrets or personal data committed.

## Community standards

Contributions are governed by the
[GitHub Community Guidelines](https://docs.github.com/en/site-policy/github-terms/github-community-guidelines),
the [GitHub Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies),
and this repo's [Code of Conduct](./CODE_OF_CONDUCT.md). Report platform-policy concerns to
[GitHub Trust & Safety](https://github.com/contact/report-content).

## License

By contributing, you agree that your contributions are licensed under this repository's
[LICENSE](../LICENSE).
