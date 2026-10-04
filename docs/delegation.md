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

## Temporary model choice for a registered agent

`pipal_delegate` accepts optional `model` and `provider` on a **new** delegation. The provider defaults to the registered agent's configured provider. This starts a separate job-scoped native session with the agent's persona and the selected model; its corrections keep the same model when addressed by `delegation_id`. The agent's `llm.json` and normal delegation session remain unchanged. Do not pass a new model on a follow-up: start a new delegation for another model. Existing approval rules still apply to costly models and parallel work.

For an interactive primary-agent TUI, `pipal agent chat <name> --model <model>` (optionally `--provider <provider>`) already passes a one-session override to Pi; it does not modify the saved `llm.json`. For example, `pipal agent chat momolty --model gpt-5.6-terra --topic research`.

## Job-scoped (ephemeral) workers

For a bounded task that needs a fresh perspective or a particular provider/model, use `pipal_delegate_ephemeral`. Unlike `pipal_delegate`, this does **not** add an agent to the registry or reuse a permanent persona or model setting. The primary specifies `role`, `provider`, `model`, `instructions`, `message`, and optionally `acceptance_criteria`:

```text
Have a one-off reviewer on my configured provider/model check this change,
then inspect its findings and request corrections if necessary.
```

The tool returns a `dg-...` delegation id. Follow up with `pipal_delegate_ephemeral` using **only** `delegation_id` and a new `message` (plus optional acceptance criteria/mode). It resumes the same worker's job-scoped context across primary-session restarts. Role, instructions, and model cannot be changed mid-job; start another job for an independent opinion. The primary can call `pipal_close_ephemeral` after review; closing rejects future turns but preserves the transcript, native sessions, background events, and reports. This is ephemeral **identity**, not ephemeral evidence.

Foreground is the default. `mode: "background"` is available with explicit owner approval, using the existing background job status/watch/report infrastructure. A correction cannot start while a previous background turn is still running. Parallel independent reviews need separate ephemeral delegations and the normal approval plan for broad multi-agent work. Provider/model must be available to the native Pi installation; Pipal does not change any registered agent's configuration.

## Saved teams from normal agent chat

Normal primary-agent chat is the default entry point. Saved teams are available as resource pools through `pipal_delegate_team`:

```text
Have mo-life-inc evaluate this independently and give me one synthesis.
```

Available members run in parallel with their team roles. The primary remains accountable for comparing contributions, requesting individual corrections, and synthesizing the outcome. This does not replace dedicated `pipal team chat`; that command remains available for long-running shared rooms.

Direct `@team:<name>` input addresses all available members. During a joined delegation, bare `@team` addresses that delegation's participants.

## Foreground and background modes

Visible foreground work is the default. It keeps tool activity transparent and interruptible. When the owner explicitly asks to run a long independent task in the background, the primary can set `mode: "background"` on `pipal_delegate`. Pipal returns a durable `dg-...` job id immediately, runs the delegate in a detached worker with an isolated native session, and shows a passive completion notice in the TUI even if the original TUI was closed and reopened.

```text
Sasha, have Ada do this in the background.
```

Use `/delegations` to list background jobs. When every participant finishes, Pipal records the result and shows one durable passive notice; it does not start an agent turn automatically. The owner can then ask the primary to review the delegation, call `pipal_delegation_status`, request corrections when needed, and report one synthesized outcome. Background mode is never selected silently for important work.

Visibility is independent from execution:

- `/watch <dg-id>` replays and streams the delegation's agent messages and tool activity.
- `/join <dg-id>` watches and lets the owner send `@agent:<name>` or `@team` follow-up interventions.
- `/detach` stops displaying activity without cancelling work.

An intervention sent while an isolated background turn is already running is treated as a persistent follow-up rather than mutating that in-flight model call.

## Durable delegation reports

Pipal provides three disclosure levels after a delegation finishes:

| Command | Report | Contract |
|---|---|---|
| `/brief <dg-id>` | Executive Summary | Decision, key evidence, material uncertainty, next actions |
| `/review <dg-id>` | Decision Review | Individual contributions, exact conclusions, provenance, manager treatment, disagreements, decision derivation |
| `/audit <dg-id>` | Audit Report | Complete evidence, source mapping, corrections, judgment trail, confidence, and unresolved uncertainty |

Each command validates the delegation and loads every participant result. The accountable primary agent must distinguish participant claims from verified facts and cannot claim independent verification unless its session contains the corresponding evidence.

Pipal saves the readable Markdown and a machine-readable record with source snapshots and SHA-256 hashes:

```text
delegations/jobs/reports/<dg-id>/
  brief.md
  brief.json
  review.md
  review.json
  audit.md
  audit.json
```

Running a report command again opens the saved version without another model call. Add `--refresh` to deliberately regenerate that report from current durable records. Existing audits in the legacy `jobs/audits/` location remain readable.

## Storage

```text
~/.pipal/agents/<primary>/topics/<topic>/delegations/
  runtime.json
  runtime-prompts/
  jobs/<dg-id>/
    job.json
    events.jsonl
    session.jsonl
  jobs/reports/<dg-id>/
    brief.md / brief.json
    review.md / review.json
    audit.md / audit.json
  <delegate>/
    transcript.jsonl
    sessions/*.jsonl
  ephemeral/<dg-id>/
    worker.json           # job-scoped role, model, instructions, closure status
    prompt.md
    transcript.jsonl
    sessions/*.jsonl      # immutable turn snapshots
  model-overrides/<dg-id>/
    model.json            # scoped registered-agent model, original settings untouched
    prompt.md
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
- `/brief`, `/review`, and `/audit` create or open durable reports at increasing levels of detail; `--refresh` regenerates one.
- `/watch`, `/join`, and `/detach` control visibility without changing execution.
