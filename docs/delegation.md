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

## Storage

```text
~/.pipal/agents/<primary>/topics/<topic>/delegations/
  runtime.json
  runtime-prompts/
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
