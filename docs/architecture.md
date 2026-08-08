# Architecture

pipal is a persistence layer on top of [pi-coding-agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent). It gives pi agents identity, memory, and continuity across sessions.

Deployment model:
- local-first
- single-user
- optional local API server

Non-goals (current):
- multi-tenant orchestration platform
- enterprise IAM/compliance system

## Overview

```
┌─────────────────────────────────────────────┐
│                   pipal                      │
│                                              │
│  CLI (agent, team, topic, task management)   │
│  Team TUI (visible multi-agent delegation)   │
│  Server (HTTP/WS via FastAPI)                │
│  Daemon (background task scheduler)          │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │          Agent (~/.pipal/agents/X)     │  │
│  │                                        │  │
│  │  AGENTS.md    - workspace rules        │  │
│  │  IDENTITY.md  - name, role, vibe       │  │
│  │  POLICY.md    - behavioral rules       │  │
│  │  USER.md      - human's profile        │  │
│  │  MEMORY.md    - durable notes          │  │
│  │  llm.json     - provider + model       │  │
│  │  topics/      - persistent topic data   │  │
│  │    X/sessions - native pi JSONL files   │  │
│  │  tasks/       - scheduled tasks         │  │
│  └────────────────────────────────────────┘  │
│                      │                       │
│                      ▼                       │
│            pi-coding-agent (pi)              │
│            (LLM interaction layer)           │
└─────────────────────────────────────────────┘
```

## How it works

When you run `pipal agent chat momo`, pipal:

1. Looks up the agent in the registry (`~/.pipal/agents.json`)
2. Reads all core markdown files and concatenates them into a system prompt
3. Selects the requested Pipal topic (`main` by default)
4. Creates a native pi session file inside that topic
5. Launches `pi` with `--append-system-prompt` and the agent's provider/model from `llm.json`

The agent's personality, memory, and rules are injected as context — pi handles the actual LLM interaction, tool execution, and session recording.

## Core files

Each agent lives in its own directory (default: `~/.pipal/agents/<name>/`). The core files define who the agent is:

| File | Purpose | Mutable by agent? |
|------|---------|-------------------|
| `AGENTS.md` | Workspace rules, file update triggers, autonomy guidelines | No |
| `IDENTITY.md` | Name, role, vibe, emoji | Yes |
| `POLICY.md` | Behavioral rules, onboarding flow, operating principles | Yes |
| `USER.md` | Human's profile — name, preferences, context | Yes |
| `MEMORY.md` | Projects, decisions, pending items, facts | Yes |
| `onboarding.md` | First-run checklist (default type only) | Yes |
| `KB.md` | Knowledge base path (kbchat type only) | No |

These files are all loaded and passed to pi as the system prompt. The agent can edit its own mutable files to learn and adapt over time.

## Agent types

pipal supports multiple agent types via templates in `src/pipal/templates/`:

- **default** — general-purpose assistant with full onboarding flow. The agent learns who you are and adapts over time.
- **kbchat** — read-only knowledge base assistant. Restricted to `read`, `grep`, `find`, `ls` tools. No onboarding. Has a `KB.md` file pointing to a knowledge base directory.

The type is stored in `.pipal_type` at creation time and determines runtime behavior (tool restrictions, extensions, onboarding).

## Topics and sessions

Pipal distinguishes between two levels:

- **Topic** — a persistent, named Pipal continuity container such as `main`, `work`, or `insurance`.
- **Session** — one native pi JSONL conversation tree inside a topic.

```
topics/
  main/
    summary.md
    summary.state.json
    topic.json
    sessions/
      20260329-183738_2698d110.jsonl
      20260330-091522_a1b2c3d4.jsonl
```

A normal chat launch creates a new native pi session. The topic's `summary.md` carries continuity across those sessions, while the rolling-summary extension also injects recent messages from the previous session. Existing legacy `sessions/<topic>/` directories are migrated automatically. See [topics.md](topics.md) for the full command and storage model.

## Extensions

pipal ships three pi extensions (TypeScript):

- **auto_greet.ts** — detects first-run vs returning user and sends appropriate greeting instruction. Uses the `onboarding.md` checklist to determine first-run status.
- **rolling_summary.ts** — on pi session shutdown, compacts the session and updates the containing topic's `summary.md`. It also loads recent messages from the previous pi session at startup.
- **kbchat_greet.ts** — greeting for kbchat agents. Reads KB config and includes KB name in the greeting.

Extensions are loaded via `--extension` when launching pi.

## Agent communication and delegation

Pipal treats registered agents as persistent communication endpoints. A normal primary-agent chat exposes two paths through the same delegate runtime:

- explicit `@agent:<name>` messages bypass the primary and run the named agent directly;
- the `pipal_delegate` tool lets the primary own an outcome through repeated messages in a persistent agent-to-agent thread;
- the `pipal_delegate_team` tool resolves a saved team into parallel persistent participants while the primary retains ownership and synthesis responsibility.

Each primary/topic/delegate tuple has an append-only transcript and an independent native Pi session. Both direct messages and delegated turns share cwd handling, event streaming, native-style tool rendering, cancellation, timeouts, and persistence. Background team member jobs share one delegation id and emit durable event streams that can be watched, joined with queued follow-up interventions, or detached without stopping execution. The primary model is instructed to frame acceptance criteria, inspect work, continue with corrections, validate completion, and report an outcome rather than relay one response. See [delegation.md](delegation.md).

## Teams

A team is a human-owned group of registered Pipal agents. It reuses topics as the conversation and continuity boundary instead of introducing a separate channel abstraction.

`pipal team chat <team> --topic <topic>` uses Pi's terminal shell with Pipal's `team_chat.ts` room extension, but no agent owns the host session. Pipal owns input dispatch, deterministic `@` routing, the roster, activity state, rendering, and the canonical append-only `transcript.jsonl`. Every participant—including the manager—runs in an isolated native Pi session with its own persona, model, tools, and history. Agents know how to inspect the shared transcript lazily when a request requires prior room context. Unaddressed messages default to the manager; explicit mentions bypass it.

The current implementation has a flat roster with a manager role and deterministic mention routing. The roster is also available from normal primary-agent chat as a delegation resource; a dedicated room is therefore an optional visible collaboration surface rather than the required way to use a team. See [teams.md](teams.md).

## Tasks and daemon

Tasks are markdown files with YAML frontmatter stored under `tasks/` (per-agent or global under `~/.pipal/tasks/`):

```yaml
---
id: daily-check
title: Daily Check
status: open
assigned_to: "momo"
schedule: "every 1d"
---

# Task

Check for pending items and summarize.
```

The daemon is a background process that wakes on interval, checks for due tasks, and runs them via `pipal task run`. Task results are logged in `runs.log` alongside each task.

## Server

pipal includes an HTTP/WebSocket server (`pipal serve`) built with FastAPI:

- **REST endpoints** — list agents, topics, native pi sessions, and chat history
- **WebSocket** — real-time chat via pi's RPC mode
- **Scoping** — restrict to a single agent/topic/session
- **Auth** — optional on loopback; required for non-local binds via `PIPAL_AUTH_TOKEN`
- **Read-only mode** — history-only, no prompts

Security note:
- `pipal serve` defaults to localhost bind for safer local usage.
- Non-local binds are refused unless `PIPAL_AUTH_TOKEN` is set; also use network protections.

## LLM configuration

Each agent has an `llm.json`:

```json
{
  "provider": "anthropic",
  "model": "claude-opus-4-6"
}
```

An optional `llm.local.json` can override settings (deep-merged). Provider and model are passed to pi via `--provider` and `--model`.

## Registry

All agents are tracked in `~/.pipal/agents.json`:

```json
{
  "agents": {
    "momo": "/Users/you/.pipal/agents/momo",
    "erwin": "/Users/you/.pipal/agents/erwin"
  }
}
```

This allows agents to live in custom paths while remaining discoverable by the CLI and server.

## Testing

```bash
uv run pytest              # unit tests (no external deps)
uv run pytest -m integration  # integration tests (needs pi installed)
uv run pytest -m ""        # all tests
```
