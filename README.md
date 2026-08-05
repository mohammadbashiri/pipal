<p align="center">
  <img src="assets/pipal_logo_cropped.png" alt="pipal logo" width="220" />
</p>

<p align="center">pipal is a Persistent Agent Layer on top of <a href="https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent">pi-coding-agent</a></p>

<p align="center">
  <a href="https://github.com/mohammadbashiri/pipal/actions/workflows/tests.yml"><img src="https://github.com/mohammadbashiri/pipal/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="python">
</p>

## Why pipal?

I tried OpenClaw, loved the persistence and personality parts, but it was too much to fully understand, and I felt uneasy about that. `pi` was the opposite — one agent, a set of tools, nothing more. I fell for the simplicity, missed the persistence, so I built pipal.

Ironically I understand OpenClaw better now. But I'm good here :)

## What is pipal?

A thin persistence layer on top of [pi-coding-agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent). It adds:

- identity, memory, and policy files for each agent
- topics that persist independently of the working directory
- native pi sessions inside topics, with rolling summaries across chats
- optional tasks, a daemon, and a local HTTP/WS server

Built for local, single-user use. One person, one machine. Not a multi-tenant platform. Not hardened for the public internet.

Largely prompted into existence and iterated through daily use.

## What pipal is not

`pipal` is not a replacement for `pi`. Models, providers, tools, and runtime behavior are `pi`'s job. pipal wraps around it.

If `pi` breaks, pipal breaks. If `pi` changes behavior, pipal follows. That's the deal.v

## Installation

Clone the repo:

```bash
git clone https://github.com/mohammadbashiri/pipal
cd pipal
```

## Quick Start

Make sure you can work/chat with the pi agent, and if pipal is installed, simply run the following to create and chat with a pipal agent:

```bash
pipal agent create momo
pipal agent chat momo
```

For additioanl information, use `--help` or just ask your agent to look into the repo and figure it out.
