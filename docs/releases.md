# Releases and Compatibility

## Compatibility matrix

`pipal` is a thin wrapper over `pi-coding-agent`, so compatibility is a release gate.

### Support policy

- Minimum supported `pi-coding-agent` version: `0.74.0`
- CI-tested targets: pinned `0.74.0` and `latest`

| pipal version | minimum supported pi version | CI-tested pi versions | notes |
|---|---|---|
| 0.1.0 | 0.66.1 | 0.66.1, latest | baseline compatibility checks in CI |
| unreleased (`main`, 0.2.0 candidate) | 0.74.0 | 0.74.0, latest | topics replace Pipal sessions; validate before tagging |

When a pipal release is cut, update this table with the exact pipal tag and the tested `pi` version(s).

## Unreleased — 0.2.0 candidate

### Added

- Native pi session listing, inspection, opening, and removal within a topic.
- Topic/session documentation and automatic legacy-storage migration tests.

### Changed

- Renamed Pipal's persistent named `session` container to `topic`; `session` now consistently means a native pi JSONL session.
- Changed storage from `sessions/<topic>/*.jsonl` to `topics/<topic>/sessions/*.jsonl`. Existing data is migrated automatically.
- Replaced Pipal topic-management commands and server routes that previously used `session` terminology. This is a compatibility-impacting CLI and API change; see [topics.md](topics.md).

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
