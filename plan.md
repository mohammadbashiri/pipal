# Plan

## Goals
- Refactor agent definition to minimal identity/policy/memory
- Add task + assignment abstractions
- Implement RPC backend for headless runs
- Replace direct `pi` wrapper with `pipal` CLI commands

## Changes
### 1) Agent definition (minimal)
- Files: AGENTS/IDENTITY/POLICY/USER/MEMORY/JOURNAL
- Move/remove: task/routine-specific files from agent directory
- Optional: journal for audit trail

### 2) Tasks + assignments
- Add global tasks under `~/.pipal/tasks` and personal tasks under `<agent>/tasks`
- Define task file schema (markdown with YAML frontmatter)
- Add assignments registry (e.g. `assignments.json` mapping task -> agent)
- Provide commands:
  - `task.list`, `task.run`, `task.status`, `task.remove`
  - Task creation/editing handled via agent skill (skills/task.md)

### 3) CLI surface (pi-agents)
- Use space-subcommands (e.g. `pi-agents task list`, `pi-agents agent ask`)
- Commands:
  - `agent create`, `agent list`, `agent ask`
  - `task list`, `task run`, `task status`, `task remove`
  - task creation/editing via agent skill
- CLI should call pi executor (RPC/CLI), not wrap pi flags directly

### 4) RPC backend
- Add RPC runner backend to drive `pi --mode rpc`
- Use for headless runs, cron, multi-agent orchestration
- Keep CLI runner as optional backend for interactive use

### 5) Persistent agent layer hardening
- Ordering guarantees: core files → summary → recent history
- Ensure tool-only turn filtering + timestamps are preserved
- Graceful handling of missing/empty summary/history files
- Summary quality controls (refresh policy, size caps)
- Config knobs for history length + summary path per agent
- Optional visibility (debug logs/flags to confirm injections)
- Token budget protection (hard caps, truncation strategy)
- Retention policy for old sessions

## Decisions
- Task file format: Markdown + YAML frontmatter
- Assignments registry: repo-root `assignments.json`
- Task storage: global tasks in `~/.pipal/tasks`, personal tasks in `<agent>/tasks`
- Agent files: uppercase (AGENTS/IDENTITY/POLICY/USER/MEMORY/JOURNAL)
- Run summaries: per-task log file (e.g. `tasks/<id>/runs.log`)
- Default storage: `~/.pipal/agents/<name>` + `~/.pipal/agents.json`, allow custom paths

## Chunks (status)
- 🟡 1) Schema + templates (agents/tasks/assignments)
  - uppercase files + AGENTS/USER ✅
  - first-run behavior + autonomy + memory rules ✅
  - task.md template + output format ✅
- 🟡 2) Rename CLI to `pipal`
- 🟡 3) CLI changes (space-subcommands + agent chat/ask)
  - auto-greet extension (first-time vs returning sessions)
  - interactive model picker on agent create
  - task list/run/status/remove ✅
  - task creation/editing via agent skill ✅
- 🟡 4) Runner changes (tasks + assignments wiring)
  - scheduled runs via daemon ✅
  - assignments registry ❌
- 🔴 5) RPC backend
- 🟡 6) Persistent agent layer hardening
  - ordering + tool-only filtering + missing files
  - summary quality controls + config knobs
  - visibility + token budget + retention policy

## Open Questions
- Memory update policy and approval flow

## Backlog
- Docs + tests for persistent agent layer
