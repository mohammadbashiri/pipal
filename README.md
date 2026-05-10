<p align="center">
  <img src="assets/pipal_logo_cropped.png" alt="pipal logo" width="220" />
</p>

<p align="center">pipal is a Persistent Agent Layer on top of <a href="https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent">pi-coding-agent</a></p>

<p align="center">
  <a href="https://github.com/mohammadbashiri/pipal/actions/workflows/tests.yml"><img src="https://github.com/mohammadbashiri/pipal/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="python">
</p>

## Why pipal?

I tried OpenClaw and loved the persistence and personality parts. But there was more running under the hood than I was comfortable with, and too much to fully understand. `pi` was the opposite — one agent, a set of tools, nothing more. I fell for the simplicity, missed the persistence, so I built pipal.

Ironically I understand OpenClaw better now. But I'm good here :)

## What is pipal?

A thin persistence layer on top of [pi-coding-agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent). It adds:
- each agent gets its own identity, memory, and policy files
- sessions stored per agent, not per directory
- rolling summaries — a session can span many chats, and you decide which ones are worth remembering for the next
- optional tasks, a daemon, and a local HTTP/WS server

Built for local, single-user use. One person, one machine. Not a multi-tenant platform, not hardened for the public internet.

Largely prompted into existence and iterated through daily use.

## What pipal is not

`pipal` is not a replacement for `pi`. Everything that matters — models, providers, tools, runtime behavior — is `pi`'s job. pipal wraps around it.

If `pi` breaks, pipal breaks. If `pi` changes behavior, pipal follows. That's the deal.

If `pi` works in your environment, `pipal` should work too.

## Installation

Before installing **pipal**, install:
- [pi-coding-agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent#quick-start)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

Install pipal:
```bash
uv tool install git+https://github.com/mohammadbashiri/pipal.git
```

Verify compatibility (canonical verification step):
```bash
pipal check-pi-compatibility
```

If the check fails, follow the suggested fixes shown by the command and rerun it.
See [docs/releases.md](docs/releases.md) for supported/tested `pi` versions.

For local development (editable install):
```bash
git clone https://github.com/mohammadbashiri/pipal
cd pipal
uv tool install -e .
```

## Quick Start

If this is your first `pi` setup, connect `pi` to a provider first using `/login` in a `pi` session (see [pi Quick Start](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent#quick-start)).

Once pi is connected to a provider, create and chat:

```bash
pipal agent create momo
pipal agent chat momo
```

## Agent types

pipal supports multiple agent types (different templates and behaviors). See [agent_types.md](agent_types.md).

## Compatibility and releases

See [docs/releases.md](docs/releases.md) for:
- pipal ↔ pi compatibility matrix
- release checklist
- changelog discipline

## Tasks

pipal supports scheduled and one-off tasks that agents can execute — manually or automatically via the daemon.

```bash
pipal task list --agent momo             # list tasks
pipal task run daily-check --agent momo  # run a task manually
pipal daemon start --agent momo --every 30m  # run due tasks on schedule
```

See [docs/tasks.md](docs/tasks.md) for full documentation: task format, scheduling syntax, model overrides, and daemon usage.

## Server

The server is optional. Core `pipal` usage is CLI-first (`agent`, `session`, `task`, `daemon`).

Run the HTTP/WS backend:
```bash
pipal serve --port 8000
```

`pipal serve` binds to `127.0.0.1` by default.
If you intentionally bind publicly (`--host 0.0.0.0`), set an auth token:
```bash
export PIPAL_AUTH_TOKEN="replace-with-long-random-token"
pipal serve --host 0.0.0.0 --port 8000
```

If WebSockets fail, reinstall pipal in the uv tool env:
```bash
uv tool install --force git+https://github.com/mohammadbashiri/pipal.git
```

On create, pipal will prompt you to pick a model from `pi --list-models` and write `llm.json`.

## Troubleshooting

### `pipal check-pi-compatibility` fails

Run:
```bash
pipal check-pi-compatibility
```

Then apply the command's suggested fix (for example: missing `llm.json`, missing pi flags, or provider auth via `/login`) and rerun.

### `pipal` command not found after install

Verify uv tool path is on your shell `PATH`, then run:
```bash
uv tool list
```

### RPC/server chat does not start

Common causes:
- no agent has `llm.json`
- provider auth not completed in `pi`
- incompatible pi version missing RPC/CLI flags

Re-run:
```bash
pipal check-pi-compatibility
```

### Server exposure safety

If the server is reachable from other machines:
- set `PIPAL_AUTH_TOKEN`
- prefer network-level protections (VPN, firewall, reverse proxy auth)
- avoid exposing unauthenticated `pipal serve` to the public internet

Pre-exposure checklist:
1. `pipal serve` is started with non-loopback host only intentionally.
2. `PIPAL_AUTH_TOKEN` is set to a long random value.
3. Access is restricted by network controls (firewall/VPN/reverse proxy).
4. TLS is terminated at a trusted ingress/reverse proxy when crossing untrusted networks.

## Storage

By default, agents are created under:
```
~/.pipal/agents/<agent_name>
```

Registry:
```
~/.pipal/agents.json
```

Tasks (personal):
```
~/.pipal/agents/<agent_name>/tasks/
```

Tasks (global):
```
~/.pipal/tasks/
```

Pass a custom base path to override the default:
```
pipal agent create momo /path/to/agents
```

## Uninstall

Run the interactive uninstaller (choose which components to remove):
```bash
pipal uninstall
```

It will optionally remove:
- the local pipal data directory (`~/.pipal`)
- the pipal CLI (`uv tool uninstall pipal`)

## Running pipal using Docker

Clone this repo (Dockerfile required).

```bash
git clone https://github.com/mohammadbashiri/pipal
cd pipal
```

Create new local data directories (so state persists across runs):
```bash
mkdir -p ~/.pipal-docker ~/.pi-docker
```

Build the image locally:
```bash
docker build -t pipal:latest .
```

We need to connect pi to a model provider. The following will open a pi session in the docker container, and you can use the `/login` command to connect pi to provider:
```bash
docker run -it --rm \
  -v ~/.pipal-docker:/home/pipal/.pipal \
  -v ~/.pi-docker:/home/pipal/.pi \
  --entrypoint pi \
  pipal:latest
```

Then you can run any pipal command via Docker (first would probably creating an agent):
```bash
docker run -it --rm \
  -v ~/.pipal-docker:/home/pipal/.pipal \
  -v ~/.pi-docker:/home/pipal/.pi \
  pipal:latest agent create momo
```

But of course you can also just chat if you already created an agent:
```bash
docker run -it --rm \
  -v ~/.pipal-docker:/home/pipal/.pipal \
  -v ~/.pi-docker:/home/pipal/.pi \
  pipal:latest agent chat momo
```

See [docs/docker.md](docs/docker.md) for more Docker commands (server, shell, etc.).
