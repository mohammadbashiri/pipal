# Pipal teams

A Pipal team is a human-owned group of registered Pipal agents. Each member has a role and its own persona, model, tools, and native Pi session. Pipal owns the shared room, transcript, routing, and TUI lifecycle; the manager is a privileged role and normal participant rather than the owner of the room.

This is an early vertical slice. It proves visible multi-agent conversation inside the familiar Pi TUI; richer hierarchy, permissions, budgets, and team management are future work.

## Create a team

Every member must already be a registered Pipal agent with an `llm.json`.

```bash
pipal team create mo-life-inc \
  --manager sasha \
  --member ada:Researcher \
  --member raven:"Risk Reviewer"
```

The manager is automatically included with the `Manager` role.

```bash
pipal team list
pipal team show mo-life-inc
pipal team remove mo-life-inc
```

## Open the team TUI

```bash
pipal team chat mo-life-inc --topic career
```

The TUI keeps Pi's normal editor, tools, Markdown rendering, session behavior, and launch working directory. The directory where `pipal team chat` is run becomes the shared working directory for manager and member tools. Native Pi sessions store their creation directory, so when a team topic is reopened from a different directory Pipal automatically forks each private session into the new working directory while preserving its history. The TUI also adds:

- team, topic, owner, and manager header
- visible roster with each agent's role and model
- shared launch working directory shown in the header
- `@team` and `@agent` autocomplete
- role/model-labelled member responses
- live member activity
- Escape or `/team-stop` cancellation
- persistent timeout and failure events
- agent-turn budgets to prevent loops

Plain messages default to the manager. Explicit owner and agent mentions are dispatched directly and deterministically by Pipal:

```text
@team Evaluate this decision together.
@ada Research the official rules.
@sasha Give me your own view first.
```

For an unaddressed substantive question, the manager can consult specialists by mentioning them before synthesizing their views. Pipal parses every owner and agent message for known `@agent` mentions, runs every mentioned agent, and returns their replies to the requesting agent so it can continue. `@team` fans out to every member. This runtime routing is deterministic and bounded by the configured agent-turn budget.

Use `--new-session` to start fresh manager and member native sessions:

```bash
pipal team chat mo-life-inc --topic career --new-session
```

Without it, Pipal resumes the latest native sessions for that team topic. A topic lock prevents two room processes from mutating the same transcript and private sessions concurrently; stale locks from crashed processes are reclaimed automatically.

## Storage

```text
~/.pipal/teams/<team>/
  team.json
  topics/<topic>/
    transcript.jsonl          # canonical shared room history
    runtime.json
    runtime-prompts/
    members/<agent>/sessions/ # independent private Pi sessions
```

The team topic is the shared continuity boundary. `transcript.jsonl` is the canonical ordered room history: launch context, owner and agent messages, and relevant visible tool activity, with attribution and timestamps. Each manager/member Pi session remains private working context.

Agents are told where the shared transcript lives and what it represents. They inspect it lazily with Pi's `read` tool when a message references earlier discussion, asks them to confirm another agent, or otherwise requires shared context; Pipal does not inject the entire transcript into every turn.

## Current limits

- one manager role and a flat team roster
- no team-specific permissions or tool budgets yet
- no team rolling-summary implementation yet
- reopening restores message history but not historical tool-block rendering
