<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/pipal_logo_darkbackground.svg">
    <img src="assets/pipal_logo_lightbackground.svg" alt="pipal logo" width="77">
  </picture>
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
- native Pi sessions inside topics, with rolling summaries across chats
- human-owned AI teams with visible multi-agent conversation in Pi's TUI
- persistent direct agent messaging and outcome-owned delegation
- an optional local HTTP/WS server

**Alpha / local-first:** pipal is designed for one person on one trusted machine. It is not a multi-tenant platform and is not hardened for the public internet. Agents run with the host user's permissions and are currently unsandboxed; treat prompts, tools, workspace files, transcripts, and reports as local data. Provider calls may incur usage charges, and `llm.json` stores the selected provider/model in plaintext (never put API keys in it). Review provider privacy, retention, and billing before delegating sensitive work.

Largely prompted into existence and iterated through daily use.

## What pipal is not

`pipal` is not a replacement for Pi. Models, providers, tools, and runtime behavior are Pi's job. pipal wraps around it.

If Pi breaks, pipal breaks. If Pi changes behavior, pipal follows. That's the deal.

## Installation

Requires [Pi coding agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent) **0.84.1 or newer** and [uv](https://docs.astral.sh/uv/). Pipal follows Pi's current extension APIs rather than emulating them for older releases.

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

Use `/watch <dg-id>`, `/join <dg-id>`, and `/detach` to control visibility of background work. `/brief <dg-id>`, `/review <dg-id>`, and `/audit <dg-id>` provide durable executive, attributed decision-review, and full evidence-trace reports. Dedicated visible rooms remain available with `pipal team chat product-team --topic planning`.

See [Pipal teams](docs/teams.md) and [persistent delegation](docs/delegation.md) for direct messaging, outcome-owned delegation, background jobs, durable reports, and the accountable primary-agent review flow. Delegation results are claims until the primary verifies them; `/brief`, `/review`, and `/audit` expose progressively more reporting detail.

Docker support is **experimental**; local installation is the supported alpha path. See [Docker usage](docs/docker.md) for isolation and networking caveats.

To learn what else pipal does, use `--help` or ask your agent to check out the repo.
