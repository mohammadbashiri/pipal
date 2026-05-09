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
│  CLI (pipal agent chat/ask/create/remove)    │
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
│  │  sessions/    - chat history (.jsonl)   │  │
│  │  tasks/       - scheduled tasks        │  │
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
3. Loads the rolling session summary (if any)
4. Launches `pi` with `--append-system-prompt` and the agent's provider/model from `llm.json`

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

## Sessions

Chat history is stored as JSONL files under `sessions/<session_name>/`:

```
sessions/
  main/
    20260329-183738_2698d110.jsonl
    20260330-091522_a1b2c3d4.jsonl
    summary.md
    summary.state.json
    session.json
```

Each chat launch creates a new `.jsonl` file. The `summary.md` is a rolling summary updated on session shutdown (via the rolling_summary extension).

## Extensions

pipal ships three pi extensions (TypeScript):

- **auto_greet.ts** — detects first-run vs returning user and sends appropriate greeting instruction. Uses the `onboarding.md` checklist to determine first-run status.
- **rolling_summary.ts** — on session shutdown, compacts the session and updates `summary.md`. Also loads recent messages from the previous session file at startup.
- **kbchat_greet.ts** — greeting for kbchat agents. Reads KB config and includes KB name in the greeting.

Extensions are loaded via `--extension` when launching pi.

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

- **REST endpoints** — list agents, sessions, session files, chat history
- **WebSocket** — real-time chat via pi's RPC mode
- **Scoping** — restrict to a single agent/session
- **Auth** — optional bearer token via `PIPAL_AUTH_TOKEN` env var
- **Read-only mode** — history-only, no prompts

Security note:
- `pipal serve` defaults to localhost bind for safer local usage.
- If you bind publicly (`0.0.0.0`/non-loopback), use `PIPAL_AUTH_TOKEN` and network protections.

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
