# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for vulnerabilities. Use GitHub private
vulnerability reporting: [open a draft advisory](https://github.com/Ranzlappen/Gamepad/security/advisories/new).

Include a summary, reproduction steps, the version or commit you tested, your assessment of
impact, and optionally a proposed fix. You can expect an acknowledgement within 3 business
days and a triage decision within 10 business days.

## Threat model

Gamepad Mapper is a local, single-user desktop tool with no network access. It injects keyboard
and mouse input on the user's behalf, so the relevant risks are:

- A malicious or malformed **imported profile** triggering unexpected input. Profiles are
  untrusted JSON, always re-validated, and can only express key, mouse-button and mouse-move
  actions.
- **Stuck or unintended input** when the app exits, pauses or a controller disconnects.
- The only system change the app makes is the optional per-user Run registry value
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\GamepadMapper`.

## Supported versions

| Version | Supported |
| --- | --- |
| Latest `main` | Yes |
| Older commits and forks | No |

## Out of scope

- Games or anti-cheat systems that block or detect synthetic input.
- Vulnerabilities in third-party dependencies that are not yet patched upstream (report those
  upstream first; a report here is welcome once a fix exists).
- Attacks that require the attacker to already control the user's account or device.

## Supply-chain commitments

| Primitive | Status |
| --- | --- |
| Actions pinned to commit SHAs | Enforced by `repo-checks.yml` |
| CodeQL (Python) and gitleaks | Every PR, push to `main`, weekly |
| Dependency review (`high` or worse blocks) | Every PR |
| OpenSSF Scorecard (floor 7.0) | Weekly and on push to `main` |
| Signed release provenance | Each release zip has a sigstore-signed SLSA attestation |

Verify a downloaded release with the GitHub CLI:

```
gh attestation verify GamepadMapper-vX.Y.Z.zip -R Ranzlappen/Gamepad
```

and compare its SHA-256 with the `.sha256` file attached to the same release.

### Waivers

None.
