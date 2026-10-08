# AI Team Playbook

How AI coding tools (Claude Code, Cursor, GitHub Copilot, Codex, ...) work on this repo without
stepping on each other. Adapted from the
[`repo-standards`](https://github.com/Ranzlappen/repo-standards) template.

## Source-of-truth hierarchy

1. [`CLAUDE.md`](../CLAUDE.md): architecture, conventions, edge cases. Read by every tool.
2. [`README.md`](../README.md): what the app is and how to use it.
3. Tool-specific entrypoints: [`.cursorrules`](../.cursorrules) for Cursor;
   `.github/copilot-instructions.md` for Copilot if one is added.
4. This playbook: coordination between tools.

When a tool-specific file disagrees with `CLAUDE.md`, `CLAUDE.md` wins and the other file is
fixed to match.

## What each tool is best at here

| Tool | Good fit | Avoid |
| --- | --- | --- |
| Claude Code | Multi-file changes, engine and threading work, test additions, PRs from issues, standards upgrades | Line-by-line autocompletion |
| Cursor | Iterating on one UI editor or panel, exploratory edits | Changes that span the engine, injector and UI at once |
| GitHub Copilot | Inline completion and boilerplate | Anything touching key release or thread ownership |
| Codex-style one-shot tools | Throwaway scripts outside the repo | Code that ships without review |

## Rules for every AI-driven change

- Conventional Commits; small, focused PRs; PR template filled in, including
  **Repo-specific risks / edge-cases**.
- `ruff check .` and `python -m pytest --cov` pass before the PR opens.
- No new runtime dependencies.
- Changes to key injection, pausing or device handling come with an engine test in
  `tests/test_engine.py`.
- No PR opens without the maintainer's explicit go-ahead.

## Hands off

- `profiles/*.json` defaults are generated from `app/defaults.py`; never hand-edit them.
- `CHANGELOG.md` is written by release-please once it is enabled; do not add entries by hand.

## Conflicts between tools

Stop and resolve at the conversation level, not by merging competing diffs. The tool that owns
the scope (table above) wins by default; the maintainer breaks ties. Record the call in the PR
description.
