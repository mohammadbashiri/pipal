<p align="center">
  <img src="assets/pipal_logo_lightbackground.svg#gh-light-mode-only" alt="pipal logo" width="77">
  <img src="assets/pipal_logo_darkbackground.svg#gh-dark-mode-only" alt="pipal logo" width="77">
</p>

<p align="center">pipal is a Persistent Agent Layer on top of the <a href="https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent"><strong>Pi coding agent</strong></a></p>

<p align="center">
  <a href="https://github.com/mohammadbashiri/pipal/actions/workflows/tests.yml"><img src="https://github.com/mohammadbashiri/pipal/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="python">
</p>

## Why pipal?

I tried OpenClaw, loved the persistence and personality, but it was too much to fully understand, and that made me uneasy. Pi was the opposite: one agent, a set of tools, nothing more. I fell for the simplicity, missed the persistence, so I built pipal.

Ironically, I understand OpenClaw better now. But I'm good here :)

## What is pipal?

A thin persistence layer on top of the [Pi coding agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent). It adds:

- identity, memory, and policy files for each agent
- topics that persist independently of the working directory
- native Pi sessions inside topics, with optional, agent-maintained summaries
- human-owned AI teams and channel-style shared multi-agent conversations in Pi's TUI
- live-session discovery, start/resume, attributed messaging, graceful quit and human handoff
- persistent direct agent messaging and outcome-owned delegation
- an optional local HTTP/WS server

**Alpha / local-first:** pipal is designed for one person on one trusted machine. It is not a multi-tenant platform and is not hardened for the public internet. Agents run with the host user's permissions and are currently unsandboxed; treat prompts, tools, workspace files, transcripts, and reports as local data. Provider calls may incur usage charges, so review provider privacy, retention, and billing before delegating sensitive work.

Largely prompted into existence and iterated through daily use.

### Models belong to Pi

Pipal adds identity, memory and persistence—not a second model/authentication layer. New chats use Pi's default model. Resuming a conversation lets Pi restore its saved model. Use Pi's `/model` and `/login` controls as usual, or pass an explicit launch override:

```sh
pipal agent chat my-agent --provider openai --model <model-id>
```

There are no agent-specific model defaults or `agent set-llm` command. Legacy `llm.json` / `llm.local.json` files no longer select an agent's model and need not be edited or migrated. Explicit per-work model overrides remain available where supported; Pipal does not silently change providers or retry failed messages.

### Conversation summaries

`/pipal:summary` asks the agent to summarize the current conversation in chat. Optional words after the command focus the request. This is an ordinary agent turn, not a separate summarizer, compaction, or save workflow.

Each topic may have a `summary.md` as a compact reference. Agents know its location and the native session directory and consult them when relevant; neither summaries nor previous-session messages are automatically injected. Saving is ordinary agent file editing with your agreement, handled conversationally—not a mandatory question or special confirmation UI. Saved notes should identify the source session and coverage point, since a resumed session can contain newer activity.

`/quit` simply quits. Pipal no longer summarizes or asks about saving during shutdown. Existing summary files and legacy metadata are preserved, but old `summary.state.json` files are not used to decide current coverage. The old `pipal topic summarize` CLI is retired; see [topics](docs/topics.md).

### Live sessions

Agents can discover participating Pi and Pipal sessions, start a normal conversation for work or human handoff, message an existing conversation and gracefully close idle work. Choose `kind: "pi"` (CLI: `pipal live start --kind pi --directory /path/to/project --json`) for plain Pi without Pipal identity, topics or memory; Pipal remains the backward-compatible default. Native UUIDs—not agent names—identify exact conversations. Type `@session:` in any participating TUI or `@` in either Pi App chat type to select a session; a leading mention sends directly without a source model turn. Other mentions remain references in an ordinary prompt.

Use `pipal live list --json` to inspect running sessions and `pipal live attach <id>` to take over the same Pipal-started TUI. Discovery, queues and replies work without Pi App or Telegram. Messages to busy recipients queue without interruption; request IDs survive disconnects, and delivery is never automatically retried. Sessions an agent did not create require explicit owner approval to close. Existing TUIs need `/reload` once. See [Live sessions](docs/live-sessions.md) for tools, CLI, identity, handoff and safety details.

## What pipal is not

`pipal` is not a replacement for Pi. Models, providers, tools, and runtime behavior are Pi's job. pipal wraps around it.

If Pi breaks, pipal breaks. If Pi changes behavior, pipal follows. That's the deal.

## Installation

Requires [Pi coding agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent) **1.4.0 or newer** and [uv](https://docs.astral.sh/uv/). Pipal follows Pi's current extension APIs rather than emulating them for older releases.

```bash
git clone https://github.com/mohammadbashiri/pipal
cd pipal
uv tool install .
pipal check-pi-compatibility
```

## Quick Start

Make sure `pi` works first. Then create and chat with a pipal agent:

```bash
pipal agent create momo
pipal agent chat momo
```

Use `pipal agent chat momo --topic main --continue` to resume the latest native Pi session in that topic. Pipal holds a per-session lock while an `agent chat` process is running; another `agent chat` cannot open the same JSONL until it exits. Plain `pi` and other launch paths do not participate in this lock.

Create a saved team from registered agents:

```bash
pipal team create product-team \
  --manager momo \
  --member researcher:Researcher \
  --member reviewer:Reviewer
```

Normal primary-agent chat is the default entrance. Address an agent directly, delegate an owned outcome, or use the saved team:

```text
@agent:researcher inspect the dependency risks.

Momo, have the researcher investigate this issue, validate the result, and report back when it is resolved.

Have product-team evaluate this in parallel and give me one synthesis.
```

Use `/pipal:delegations` to list background work and `/pipal:delegation <dg-id>` for status and available actions. Add `watch` or `join` to follow its activity; `/pipal:detach` stops watching without cancelling. Add `brief`, `review`, or `audit` to create/open durable reports; add `cancel` to stop active workers. Dedicated visible rooms remain available with `pipal team chat product-team --topic planning`.

For a flat shared room—where agents act only when mentioned—create a channel:

```bash
pipal channel create product --member momo:Builder --member reviewer:Reviewer
pipal channel chat product --topic planning
```

See [Pipal channels](docs/channels.md), [Pipal teams](docs/teams.md), and [delegation](docs/delegation.md) for direct messaging, persistent and one-off workers, background jobs, durable reports, and the accountable primary-agent review flow. [ClickClack integration](docs/clickclack.md) explains how to connect ClickClack bots to local Pipal agents. Delegation results are claims until the primary verifies them; the `brief`, `review`, and `audit` actions expose progressively more reporting detail.

Docker support is **experimental**; local installation is the supported alpha path. See [Docker usage](docs/docker.md) for isolation and networking caveats.

For development setup and test commands, see [Running tests](docs/testing.md).

To learn what else pipal does, use `--help` or ask your agent to check out the repo.
