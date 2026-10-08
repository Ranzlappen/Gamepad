# Governance

How **Gamepad Mapper** is run. Short on purpose: anything not covered here lives in
[`CONTRIBUTING.md`](./CONTRIBUTING.md), [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) or
[`SECURITY.md`](./SECURITY.md). Adapted from the
[`repo-standards`](https://github.com/Ranzlappen/repo-standards) v3 governance template.

## Roles

- **Maintainer**: [@Ranzlappen](https://github.com/Ranzlappen), listed in [`CODEOWNERS`](./CODEOWNERS).
  Merges PRs, cuts releases, edits branch protection. New maintainers are added by PR to
  `CODEOWNERS`.
- **Contributors**: anyone who opens an issue or PR. Reviews are welcome and weighed.
- **Users**: everyone else. Bug reports and feature requests go through the
  [issue forms](./ISSUE_TEMPLATE/).

## Decision-making

Decisions happen in PR review. With a single maintainer, the maintainer decides; reasons for
non-obvious calls are written in the PR so later contributors can see them. Style questions are
settled by ruff and the existing patterns, not by debate.

## Contribution lifecycle

1. **Issue first** for anything beyond a small fix.
2. **Branch from `main`** (`feat/...`, `fix/...`, `docs/...`).
3. **Open a PR** using the [PR template](./PULL_REQUEST_TEMPLATE.md); keep it reviewable in one
   sitting.
4. **CI must be green** before review.
5. **Squash-merge** with a Conventional Commits title; release-please reads those titles to build
   the changelog and pick the next version.

## Branch protection for `main`

Configure under **Settings > Rules > Rulesets > New branch ruleset**, enforcement **Active**,
target **Include default branch**:

- **Restrict deletions** and **Block force pushes**.
- **Require linear history** (squash-merge only).
- **Require a pull request before merging**, with conversation resolution required.
  - **Required approvals: 0 while there is a single maintainer.** GitHub never lets an author
    approve their own PR, and PRs opened by Claude Code are authored by the maintainer's account,
    so 1 approval (or "Require review from Code Owners") would block every merge. Raise it to 1
    and turn on Code Owners review when a second maintainer joins.
- **Require status checks to pass** and **require branches to be up to date**. Required checks
  (they appear in the picker after their first run):
  - `Lint and test (ubuntu-latest, py3.11)`, `Lint and test (ubuntu-latest, py3.13)`,
    `Lint and test (windows-latest, py3.11)`, `Lint and test (windows-latest, py3.13)`
  - `actionlint (workflows)`, `lychee (offline link check)`, `uses-line SHA-pinning lint`
  - `CodeQL (python)`, `Gitleaks secret scan`, `Dependency review`
- **Bypass list: empty**, so the rules also apply to administrators.
- **Require signed commits** only once every committer (including the account Claude Code pushes
  with) signs commits; otherwise merges are blocked.

## Supply-chain governance

- **OpenSSF Scorecard floor: 7.0.** A lower score at
  [securityscorecards.dev](https://securityscorecards.dev/viewer/?uri=github.com/Ranzlappen/Gamepad)
  is a regression to fix within 30 days or to waive publicly in [`SECURITY.md`](./SECURITY.md).
- **Dependency review is required** on every PR; a high-or-above CVE blocks the merge until it is
  patched, pinned to a fixed range, or waived in the PR description with the CVE ID.
- **CodeQL covers every language in the repo** (currently Python).
- **Every action is pinned to a commit SHA**, enforced by `repo-checks.yml`.
- **Releases are attested**: release bundles carry a sigstore-signed SLSA provenance
  attestation (see [`SECURITY.md`](./SECURITY.md) for how to verify).
- **Dependabot** opens the update PRs; a maintainer reviews and merges them. No auto-merge.
- **Waivers are public**: any bypass of the rules above is recorded in `SECURITY.md` with a
  reason and a review date.

## Triage and releases

- New issues are acknowledged within 7 days: the label becomes `bug` or `enhancement`, with a
  one-line response. `question`-type issues are closed with a pointer to the README or, once
  enabled, Discussions.
- Labels in use: `bug`, `enhancement`, `question`, `dependencies`, `python`, `github-actions`,
  `security` (never public; see `SECURITY.md`), `out-of-scope` and `from-claude` (findings
  filed by Claude Code).
- Releases are cut by merging the release-please PR, once `RELEASE_PLEASE_ENABLED` is set.
- Security fixes ship on their own PR, ahead of other work.
