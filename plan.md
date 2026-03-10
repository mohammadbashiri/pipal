# Plan

## Goals
- Refactor agent definition to minimal identity/policy/memory
- Add task + assignment abstractions
- Implement RPC backend for headless runs
- Replace direct `pi` wrapper with `pi-agents` CLI commands

## Changes
### 1) Agent definition (minimal)
- Keep: `identity.md`, `policy.md` (rename from principles?), `memory.md`
- Move/remove: task/routine-specific files from agent directory
- Optional: `journal.jsonl` for audit trail

### 2) Tasks + assignments
- Add top-level `tasks/` directory
- Define task file schema (markdown with optional frontmatter)
- Add assignments registry (e.g. `assignments.json` mapping task -> agent)
- Provide commands:
  - `task.create`, `task.list`, `task.assign`, `task.run`, `task.status`

### 3) CLI surface (pi-agents)
- Use space-subcommands (e.g. `pi-agents task list`, `pi-agents agent ask`)
- Commands:
  - `agent create`, `agent list`, `agent ask`
  - `task create`, `task list`, `task assign`, `task run`, `task status`
- CLI should call pi executor (RPC/CLI), not wrap pi flags directly

### 4) RPC backend
- Add RPC runner backend to drive `pi --mode rpc`
- Use for headless runs, cron, multi-agent orchestration
- Keep CLI runner as optional backend for interactive use

## Decisions
- Task file format: Markdown + YAML frontmatter
- Assignments registry: repo-root `assignments.json`
- Agent files: keep `identity.md`, rename `principles.md` -> `policy.md`, drop `strategy.md`
- Run summaries: per-task (e.g. `tasks/<id>/runs/`)
- Default storage: central store (e.g. `~/.pi/agents`, `~/.pi/tasks`) but allow custom paths

## Chunks (status)
- 🟠 1) Schema + templates (agents/tasks/assignments)
  - updated identity/policy templates for first‑run behavior
- 🟠 2) Rename CLI to `pal`
- 🟠 3) CLI changes (space-subcommands + agent chat/ask)
  - auto-greet extension for clean first-run chat
- 🔴 4) Runner changes (tasks + assignments wiring)
- 🔴 5) RPC backend

## Open Questions
- Memory update policy and approval flow
