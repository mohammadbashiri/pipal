# Milestone: M1 - Thin Layer Foundation

Goal: make `pipal` a solid, useful, and extensible thin layer over `pi` with zero unnecessary platform complexity.

## Scope
- Installation and compatibility flow that works first try.
- Clear contract: what pipal changes vs what remains pure pi behavior.
- Hardened thin-layer paths only (scaffold, registry, sessions, tasks/daemon).
- Optional server clearly documented and minimally secure by default.
- Compatibility and quality signals for public OSS trust.

## Success criteria
- New user with working `pi` can install and run `pipal agent create` + `pipal agent chat` in <10 minutes.
- README clearly states scope boundaries and operational model.
- Tests cover failure-prone wrapper behavior.
- Versioned compatibility matrix exists and is updated each release.
