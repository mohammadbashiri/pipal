<p align="center">
  <img src="assets/pipal_logo_cropped.png" alt="pipal logo" width="220" />
</p>

<p align="center">pipal is a Persistent Agent Layer on top of <a href="https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent">pi-coding-agent</a></p>

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

## Tasks

pipal supports scheduled and one-off tasks that agents can execute.

```bash
# List all tasks
pipal task list

# List tasks for a specific agent
pipal task list --agent momo

# Run a task
pipal task run <task_id> --agent momo

# Check task status
pipal task status

# Remove a task
pipal task remove <task_id> --agent momo
```

Tasks are stored as markdown files with YAML frontmatter under `tasks/` (per-agent or global). Use the daemon to run scheduled tasks automatically:

```bash
# Start daemon (runs due tasks on interval)
pipal daemon start --agent momo --every 30m

# Check daemon status
pipal daemon status --agent momo

# View daemon logs
pipal daemon logs --agent momo

# Stop daemon
pipal daemon stop --agent momo
```
