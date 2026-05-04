# Server Safety Defaults + Optionality

## Why
Server should not weaken project security posture while remaining optional.

## Deliverables
- Update docs to recommend localhost-only bind for default usage.
- Add explicit auth guidance (`PIPAL_AUTH_TOKEN`) and warning for public exposure.
- Review and tighten default behavior where feasible without breaking local workflows.
- Add SECURITY.md with threat model for current scope.

## Acceptance criteria
- Users can understand safe vs unsafe deployment in one read.
- Security expectations and current limitations are documented.
