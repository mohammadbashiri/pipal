# Hardening: Tasks + Daemon

## Why
Scheduled tasks are core utility; daemon edge failures can silently erode trust.

## Deliverables
- Improve task run error paths and parse failures with explicit statuses.
- Add tests for schedule parsing and due-calculation edge cases.
- Ensure daemon logs are consistent and actionable.
- Document daemon limits and expected behavior clearly.

## Acceptance criteria
- Task errors are never ambiguous.
- Daemon behavior under missing binaries/timeouts is covered by tests.
