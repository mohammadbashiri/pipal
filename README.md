<p align="center">
  <img src="assets/pipal_logo_cropped.png" alt="pipal logo" width="220" />
</p>

<p align="center">pipal is a Persistent Agent Layer on top of <a href="https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent">pi-coding-agent</a></p>

<p align="center">
  <a href="https://github.com/mohammadbashiri/pipal/actions/workflows/tests.yml"><img src="https://github.com/mohammadbashiri/pipal/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="python">
</p>

## What is pipal?

Simply put, pipal is a wrapper around [pi-coding-agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent) that helps agents adapt to you and grow with you, by giving pi agents persistence, memory, and personality.


## Installation

Before installing **pipal** you need to have both [pi-coding-agent](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent#quick-start) and [uv](https://docs.astral.sh/uv/getting-started/installation/) installed.


Install pipal (recommended):
```bash
uv tool install git+https://github.com/mohammadbashiri/pipal.git
```

For local development (editable install):
```bash
git clone https://github.com/mohammadbashiri/pipal
cd pipal
uv tool install -e .
```

## Quick Start

If you are installing pi-coding-agent for the first time, you would need to first connect to a model provider using the `/login` command in a pi session - simply follow the instructions in the [pi-coding-agent's Quick Start](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent#quick-start).

Once pi is connected to a provider, you can create a pipal agent and start chatting with it:

```bash
pipal agent create momo
pipal agent chat momo
```

## Agent types

pipal supports multiple agent types (different templates and behaviors). See [agent_types.md](agent_types.md).

## Tasks

pipal supports scheduled and one-off tasks that agents can execute — manually or automatically via the daemon.

```bash
pipal task list --agent momo             # list tasks
pipal task run daily-check --agent momo  # run a task manually
pipal daemon start --agent momo --every 30m  # run due tasks on schedule
```

See [docs/tasks.md](docs/tasks.md) for full documentation: task format, scheduling syntax, model overrides, and daemon usage.

## Server

Run the HTTP/WS backend:
```bash
pipal serve --port 8000
```

If WebSockets fail, reinstall pipal via `uv tool install -e .` (it must install into the tool env).

On create, pipal will prompt you to pick a model from `pi --list-models` and write `llm.json`.

## Storage

By default, agents are created under:
```
~/.pipal/agents/<agent_name>
```

Registry:
```
~/.pipal/agents.json
```

Pass a custom base path to override the default:
```
pipal agent create momo /path/to/agents
```

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

## Uninstall

Run the interactive uninstaller (choose which components to remove):
```bash
pipal uninstall
```

It will optionally remove:
- the local pipal data directory (`~/.pipal`)
- the pipal CLI (`uv tool uninstall pipal`)
