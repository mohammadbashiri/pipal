# Hardening: Scaffold, Registry, Sessions

## Why
These are the primary persistence surfaces and reputation-critical for reliability.

## Deliverables
- Tighten path validation and error messaging for agent create/remove/list.
- Add tests for registry migration and relative/absolute path edge cases.
- Add tests for session metadata creation/update/title behavior.
- Improve resilience for malformed session files.

## Acceptance criteria
- Wrapper behavior is deterministic across malformed input scenarios.
- Test coverage includes known edge cases in registry/session paths.
