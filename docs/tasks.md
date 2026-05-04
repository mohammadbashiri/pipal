# Tasks

Tasks are markdown files with YAML frontmatter that agents can execute — manually or on a schedule via the daemon.

## Task file format

```yaml
---
id: daily-check
title: Daily Check
status: open
assigned_to: "momo"
schedule: "every 1d"
provider: null
model: null
---

# Task

Describe the goal, context, and acceptance criteria here.

## Output format
Return exactly one line:
- TASK_OK changes="..." next_steps="..."
- TASK_FAIL reason="..."
```

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | auto | Slug derived from title. Set automatically. |
| `title` | yes | Human-readable task name. |
| `status` | yes | `open` or `closed`. |
| `assigned_to` | yes (for global tasks) | Agent name to run this task. |
| `schedule` | no | How often to run (see [Scheduling](#scheduling)). |
| `provider` | no | Override the agent's default LLM provider for this task. |
| `model` | no | Override the agent's default model for this task. |
| `enabled` | no | `true` (default) or `false` to disable without deleting. |

### Model override

By default a task runs with the agent's configured `llm.json`. You can override this per-task — useful for running expensive tasks with a cheaper model, or running specialist tasks with a more capable one:

```yaml
---
id: code-review
title: Code Review
assigned_to: "momo"
schedule: "every 1d"
provider: "ollama"
model: "qwen3-coder:30b"
---
```

## Task locations

Tasks can be **personal** (belong to a specific agent) or **global** (shared across all agents):

```
~/.pipal/agents/<name>/tasks/<task-id>/task.md   # personal
~/.pipal/tasks/<task-id>/task.md                  # global
```

Global tasks must have `assigned_to` set so the daemon knows which agent to run them with.

## CLI commands

```bash
# List all tasks
pipal task list

# List tasks for a specific agent
pipal task list --agent momo

# List global tasks only
pipal task list --global

# Run a task manually
pipal task run daily-check --agent momo

# Check task status (last run, result)
pipal task status --agent momo

# Remove a task
pipal task remove daily-check --agent momo
```

## Scheduling

Use the `schedule` field to run tasks automatically via the daemon.

### Syntax

| Example | Meaning |
|---------|---------|
| `every 30m` | Every 30 minutes |
| `every 1h` | Every hour |
| `every 2h30m` | Every 2.5 hours |
| `every 1d` | Every day |
| `every 1w` | Every week |

If `schedule` is empty or omitted, the task only runs when triggered manually.

## Daemon

The daemon runs in the background, checks for due tasks, and executes them automatically.

```bash
# Start daemon (runs due tasks every 30 minutes)
pipal daemon start --agent momo --every 30m

# Check daemon status
pipal daemon status --agent momo

# View daemon logs
pipal daemon logs --agent momo

# Stop daemon
pipal daemon stop --agent momo
```

The daemon fires at precise absolute intervals — if a task takes 10 seconds to run with a 60-second interval, the next tick still fires at 60 seconds, not 70.

### Runtime limits and failure signals

- Each task run has a 5-minute timeout.
- If a task process exits non-zero, the daemon logs a `TASK_FAIL` line with the exit code.
- If a task produces no output, the daemon logs `TASK_FAIL No output from task run`.

## Output format

Tasks must return exactly one line in the following format:

```
TASK_OK changes="what was done" next_steps="what to do next"
TASK_FAIL reason="why it failed"
```

This is enforced by the task template and logged in `runs.log` alongside each task directory.

## Example task

A daily task that checks for uncommitted git changes:

```markdown
---
id: git-check
title: Git Status Check
status: open
assigned_to: "momo"
schedule: "every 1d"
---

# Task

Check if there are any uncommitted changes in ~/Projects. If there are,
list the repositories and summarize what is uncommitted.

## Output format
Return exactly one line:
- TASK_OK changes="checked repos" next_steps="commit pending changes in X"
- TASK_FAIL reason="..."
```
