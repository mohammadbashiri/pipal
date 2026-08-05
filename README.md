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
- optional tasks, a daemon, and a local HTTP/WS server

Built for local, single-user use. One person, one machine. Not a multi-tenant platform. Not hardened for the public internet.

Largely prompted into existence and iterated through daily use.

## What pipal is not

`pipal` is not a replacement for Pi. Models, providers, tools, and runtime behavior are Pi's job. pipal wraps around it.

If Pi breaks, pipal breaks. If Pi changes behavior, pipal follows. That's the deal.

## Installation

Requires the [Pi coding agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent) and [uv](https://docs.astral.sh/uv/).

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

To learn what else pipal does, use `--help` or ask your agent to check out the repo.
