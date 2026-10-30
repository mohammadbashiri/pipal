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

`pipal_delegate` accepts optional `model` and `provider` on a **new** delegation. Without an explicit override, Pi selects the provider/model; registered agents have no model defaults. This starts a separate job-scoped native session with the agent's persona and the selected model; its corrections keep the same model when addressed by `delegation_id`. Pi's defaults and the normal delegation session remain unchanged. Do not pass a new model on a follow-up: start a new delegation for another model. Existing approval rules still apply to costly models and parallel work.

For an interactive primary-agent TUI, `pipal agent chat <name> --model <model>` (optionally `--provider <provider>`) already passes a one-session override to Pi; it does not modify Pi's defaults. For example, `pipal agent chat momolty --model gpt-5.6-terra --topic research`.

## Job-scoped (ephemeral) workers

For a bounded task that needs a fresh perspective or a particular provider/model, use `pipal_delegate_ephemeral`. Unlike `pipal_delegate`, this does **not** add an agent to the registry or reuse a permanent persona or model setting. The primary supplies a `message` and may specify `role`, `provider`, `model`, `instructions`, and `acceptance_criteria`. Omitted provider/model inherit only an explicit primary-launch override, if present; otherwise Pi selects its defaults. A model-only override lets Pi resolve the provider. Role defaults to General assistant and instructions to evidence-based work. A different provider requires an explicit model. Pi's separate `subagent` tool is **not** Pipal delegation:

```text
Have a one-off reviewer on my configured provider/model check this change,
then inspect its findings and request corrections if necessary.
```

The tool returns a `dg-...` delegation id. Follow up with `pipal_delegate_ephemeral` using **only** `delegation_id` and a new `message` (plus optional acceptance criteria/mode). It resumes the same worker's job-scoped context across primary-session restarts. Role, instructions, and model cannot be changed mid-job; start another job for an independent opinion. The primary can call `pipal_close_ephemeral` after review; closing rejects future turns but preserves the transcript, native sessions, background events, and reports. This is ephemeral **identity**, not ephemeral evidence.

Background is the default for ephemeral workers, using the existing background job status/watch/report infrastructure. The tool returns a delegation id immediately so the owner can continue chatting. Use `mode: "foreground"` when explicitly requested to wait for the worker. Registered-agent and team delegations still default to foreground. A correction cannot start while a previous background turn is still running. Parallel independent reviews need separate ephemeral delegations and the normal approval plan for broad multi-agent work. Provider/model must be available to the native Pi installation; Pipal does not change any registered agent's configuration.

## Saved teams from normal agent chat

Normal primary-agent chat is the default entry point. Saved teams are available as resource pools through `pipal_delegate_team`:

```text
Have mo-life-inc evaluate this independently and give me one synthesis.
```

Available members run in parallel with their team roles. The primary remains accountable for comparing contributions, requesting individual corrections, and synthesizing the outcome. This does not replace dedicated `pipal team chat`; that command remains available for long-running shared rooms.

Direct `@team:<name>` input addresses all available members. During a joined delegation, bare `@team` addresses that delegation's participants.

## Shared session foundation

Delegation is a higher-level workflow over the [shared Pi/Pipal session primitives](live-sessions.md). Both foreground and background turns use `session_worker.py`: one bounded native **RPC** process, the shared presence registry, idle inbox, durable request/result records, and exact runtime-bound shutdown. There is no separate print-prompt delivery path and no forced tmux/TUI for workers. The normal session advisory lock prevents concurrent writers.

Delegation still owns persona/task instructions, persistent threads and isolated background snapshots, job leases, owner-approved cancellation, joined follow-ups, reviews and reports. Cancellation may abort its own active worker; ordinary cross-session Quit continues to refuse busy work. Native tool/text/usage events stream for the delegated request only. Other peer requests can queue and drain within the worker's existing timeout, but never become the delegation's answer or extend its lifetime indefinitely.

Foreground results and completed transcript messages carry `live_session`; background `job.json` and status include it as soon as startup succeeds. Its native `session_id`, `runtime_id` and durable `request_id` link delegation evidence to the same session/result APIs used elsewhere. This reference is persisted before first delivery, including uncertain acknowledgements. No delivery is automatically retried.

Background launch captures peer attribution so closing the primary TUI does not invalidate already-approved work. Captured identity is **not** owner approval. Headless UI confirmation/input requests are cancelled rather than auto-approved; agents must return a blocker when human consent is needed. Completion remains passive and never starts a primary model turn. Existing job files, transcripts, session histories and reports remain readable; no historical records are migrated or rewritten.

## Foreground and background modes

Visible foreground work is the default. It keeps tool activity transparent and interruptible. When the owner explicitly asks to run a long independent task in the background, the primary can set `mode: "background"` on `pipal_delegate`. Pipal returns a durable `dg-...` job id immediately, runs the delegate in a detached worker with an isolated native session, and shows a passive completion notice in the TUI even if the original TUI was closed and reopened.

```text
Sasha, have Ada do this in the background.
```

Use `/pipal:delegations` to list background jobs. `/pipal:delegation <dg-id>` shows status and available actions without starting a model turn. When every participant finishes, Pipal records the result and shows one durable passive notice; it does not start an agent turn automatically. The owner can then ask the primary to review the delegation, call `pipal_delegation_status`, request corrections when needed, and report one synthesized outcome. Background mode is never selected silently for important work.

Visibility is independent from execution:

- `/pipal:delegation <dg-id> watch` replays and streams the delegation's agent messages and tool activity.
- `/pipal:delegation <dg-id> join` watches and lets the owner send `@agent:<name>` or `@team` follow-up interventions.
- `/pipal:detach` stops displaying activity without cancelling work.

An intervention sent while an isolated background turn is already running is treated as a persistent follow-up rather than mutating that in-flight model call.

## Durable delegation reports

Pipal provides three disclosure levels after a delegation finishes. These report on delegated work, not the current conversation; `/pipal:summary` is the separate conversational shortcut:

| Command | Report | Contract |
|---|---|---|
| `/pipal:delegation <dg-id> brief` | Executive Summary | Decision, key evidence, material uncertainty, next actions |
| `/pipal:delegation <dg-id> review` | Decision Review | Individual contributions, exact conclusions, provenance, manager treatment, disagreements, decision derivation |
| `/pipal:delegation <dg-id> audit` | Audit Report | Complete evidence, source mapping, corrections, judgment trail, confidence, and unresolved uncertainty |

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
- `/pipal:delegations` lists durable background jobs and groups team members under one delegation id.
- `/pipal:delegation <dg-id> cancel` terminates all active workers in that delegation.
- `/pipal:delegation <dg-id> brief|review|audit` creates or opens a durable report; `--refresh` explicitly regenerates it.
- The `watch` and `join` delegation actions, and `/pipal:detach`, control visibility without changing execution.
- Old unnamespaced Pipal command names are no longer registered. Native Pi commands remain unchanged.
