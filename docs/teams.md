# Pipal teams

A Pipal team is a human-owned group of registered Pipal agents. Each member has a role and its own persona, model, tools, and native Pi session. The manager is the primary participant in the Pi TUI and can delegate to other members through the `team_delegate` tool.

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

The TUI keeps Pi's normal editor, tools, Markdown rendering, and session behavior, and adds:

- team, topic, owner, and manager header
- visible roster with each agent's role and model
- `@team` and `@agent` autocomplete
- role/model-labelled member responses
- live member activity
- delegation budgets to prevent loops

Plain messages go to the manager. Direct mentions are routed through the manager:

```text
@team Evaluate this decision together.
@ada Research the official rules.
@sasha Give me your own view first.
```

Substantial questions can cause the manager to call several members in parallel before synthesizing their views. Member responses are tool results in the manager's native Pi session, so they are visible to the user and available to the manager's model context.

Use `--new-session` to start fresh manager and member native sessions:

```bash
pipal team chat mo-life-inc --topic career --new-session
```

Without it, Pipal resumes the latest native sessions for that team topic.

## Storage

```text
~/.pipal/teams/<team>/
  team.json
  topics/<topic>/
    runtime.json
    runtime-prompts/
    sessions/                 # manager-facing Pi TUI session
    members/<agent>/sessions/ # independent member Pi sessions
```

The team topic is the shared continuity boundary. The manager-facing session contains the canonical visible discussion; each member session preserves that member's delegated conversation history.

## Current limits

- one manager and a flat member list
- delegation is manager-mediated
- no team-specific permissions or tool budgets yet
- no team rolling-summary implementation yet
- member responses stream as visible team tool cards rather than independent top-level Pi assistant messages
