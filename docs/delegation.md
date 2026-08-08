# Persistent agent delegation

A normal Pipal agent chat can use other registered Pipal agents in two ways.

## Direct namespaced messages

Explicit `@agent:<name>` mentions bypass the primary agent and address registered agents directly:

```text
@agent:ada inspect the dependency file and report the risks.
```

Multiple namespaced mentions run in parallel. The TUI autocompletes registered names, displays native-style agent-labelled tool blocks, and keeps one persistent delegate session per primary agent, topic, and delegate.

## Outcome-owned delegation

The primary agent has a `pipal_delegate` tool. Natural requests such as:

```text
Sasha, have Ada investigate this failure and get it resolved.
```

allow the primary to select a registered agent, frame a concrete task and acceptance criteria, inspect the response, and continue the same persistent thread with follow-up or correction requests.

The primary owns the outcome. It should not act as a one-shot relay. It is instructed to:

1. frame the goal, context, and acceptance criteria;
2. delegate to an appropriate persistent Pipal agent;
3. inspect claims and artifacts;
4. request corrections or additional work;
5. validate completion where practical;
6. report the finished outcome or a genuine blocker.

Critical or external actions still require the owner's normal approval.

## Saved teams from normal agent chat

Normal primary-agent chat is the default entry point. Saved teams are available as resource pools through `pipal_delegate_team`:

```text
Have mo-life-inc evaluate this independently and give me one synthesis.
```

Available members run in parallel with their team roles. The primary remains accountable for comparing contributions, requesting individual corrections, and synthesizing the outcome. This does not replace dedicated `pipal team chat`; that command remains available for long-running shared rooms.

Direct `@team:<name>` input addresses all available members. During a joined delegation, bare `@team` addresses that delegation's participants.

## Foreground and background modes

Visible foreground work is the default. It keeps tool activity transparent and interruptible. When the owner explicitly asks to run a long independent task in the background, the primary can set `mode: "background"` on `pipal_delegate`. Pipal returns a durable `dg-...` job id immediately, runs the delegate in a detached worker with an isolated native session, and reports completion in the TUI even if the original TUI was closed and reopened.

```text
Sasha, have Ada do this in the background.
```

Use `/delegations` to list background jobs. When every participant finishes, Pipal wakes the primary agent with one durable completion event. The primary calls `pipal_delegation_status` for the entire delegation, reviews results and failures, requests corrections when needed, and reports one synthesized outcome. If the TUI was closed, this review starts when the topic is reopened. Background mode is never selected silently for important work.

Visibility is independent from execution:

- `/watch <dg-id>` replays and streams the delegation's agent messages and tool activity.
- `/join <dg-id>` watches and lets the owner send `@agent:<name>` or `@team` follow-up interventions.
- `/detach` stops displaying activity without cancelling work.

An intervention sent while an isolated background turn is already running is treated as a persistent follow-up rather than mutating that in-flight model call.

## Storage

```text
~/.pipal/agents/<primary>/topics/<topic>/delegations/
  runtime.json
  runtime-prompts/
  jobs/<dg-id>/
    job.json
    session.jsonl
  <delegate>/
    transcript.jsonl
    sessions/*.jsonl
```

The transcript is the durable direct/delegation thread. The delegate's native Pi session preserves private working context. Reopening the primary topic resumes the latest delegate session, forking it automatically if the launch working directory changed.

## Controls

- Escape cancels active direct `@agent:` work.
- Native Pi cancellation applies to `pipal_delegate` tool calls.
- Agent turns time out after five minutes by default.
- Repeated delegation calls are bounded per primary turn.
- `/delegations` lists durable background jobs and groups team members under one delegation id.
- `/cancel-delegation <dg-id>` terminates all active workers in that delegation.
- `/watch`, `/join`, and `/detach` control visibility without changing execution.
