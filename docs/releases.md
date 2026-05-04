# Releases and Compatibility

## Compatibility matrix

`pipal` is a thin wrapper over `pi-coding-agent`, so compatibility is a release gate.

| pipal version | tested pi-coding-agent version | notes |
|---|---|---|
| 0.1.0 | latest (CI `PI_VERSION=latest`) | baseline compatibility checks in CI |
| unreleased (`main`) | latest (CI `PI_VERSION=latest`) | validate before tagging |

When a pipal release is cut, update this table with the exact pipal tag and the tested `pi` version(s).

## Release checklist

Run these steps before creating a release tag:

1. Ensure milestone issues are complete and merged to `main`.
2. Update docs for any CLI/behavior changes (`README.md`, `docs/*.md`).
3. Run full tests locally:
   - `uv run pytest -q`
4. Run compatibility check locally:
   - `pipal check-pi-compatibility`
5. Verify quickstart flow on a clean environment:
   - install `pipal`
   - `pipal check-pi-compatibility`
   - `pipal agent create <name>`
   - `pipal agent chat <name>`
6. Update compatibility matrix in this file with tested versions.
7. Add release notes summary (highlights + any behavior changes).
8. Tag and publish release.

## Changelog discipline

For each release, include:
- Added: new capabilities
- Changed: behavior changes (including defaults)
- Fixed: bug fixes
- Security: relevant security hardening/guidance

If a change may affect existing scripts or workflows, call it out explicitly as a compatibility-impacting change.
