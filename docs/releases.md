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

**Release position:** local-first alpha for one trusted user and machine. The host runtime is unsandboxed, agents inherit host permissions, and provider requests may incur costs. Treat transcripts/reports and `llm.json` (provider/model metadata in plaintext) as local data; do not expose the service publicly or place secrets in agent files. Docker remains experimental unless the package and runtime path have been tested in CI for the target environment.

### Added

- Native pi session listing, inspection, opening, and removal within a topic.
- Topic/session documentation and automatic legacy-storage migration tests.
- Direct messaging, outcome-owned delegation, background delegation controls, and durable executive/decision/audit reporting with accountable primary-agent synthesis.
- Transactional agent creation with noninteractive `--provider`/`--model` setup; incomplete flag pairs fail before filesystem changes.

### Changed

- Renamed Pipal's persistent named `session` container to `topic`; `session` now consistently means a native pi JSONL session.
- Changed storage from `sessions/<topic>/*.jsonl` to `topics/<topic>/sessions/*.jsonl`. Existing data is migrated automatically.
- Replaced Pipal topic-management commands and server routes that previously used `session` terminology. This is a compatibility-impacting CLI and API change; see [topics.md](topics.md).
- `pipal agent create` remains interactive when both LLM flags are omitted; `--provider` and `--model` must now be supplied together for noninteractive creation.
- Non-loopback server binds now require an authentication token of at least 32 characters. REST and WebSocket authentication use strict Bearer headers; WebSocket query-string tokens are no longer accepted. CORS is disabled by default and supports only explicit configured HTTP(S) origins. When authentication is configured, `/health` is authenticated too. See `SECURITY.md` for browser WebSocket and reverse-proxy implications.

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
6. Verify package delivery:
   - `uv build`
   - install the wheel into a brand-new virtual environment
   - run `pip check` and `pipal --help`
7. Exercise delegation/reporting: direct message, foreground delegation, background `/watch`/`/join`/`/detach`, and `/brief`/`/review`/`/audit`; verify the primary reviews participant results before reporting.
8. Confirm local-first safety wording, unsandboxed host-permission boundaries, plaintext config handling, provider cost/privacy guidance, and that Docker is explicitly experimental (unless target Docker behavior is CI-tested).
9. Update compatibility matrix in this file with tested versions.
10. Add release notes summary (highlights + any behavior changes).
11. Tag and publish release.

## Changelog discipline

For each release, include:
- Added: new capabilities
- Changed: behavior changes (including defaults)
- Fixed: bug fixes
- Security: relevant security hardening/guidance

If a change may affect existing scripts or workflows, call it out explicitly as a compatibility-impacting change.
