<p align="center">
  <img src="assets/pipal_logo_cropped.png" alt="pipal logo" width="220" />
</p>

<p align="center">π-pal is a Persistant Agent Layer on top of <a href="https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent">pi-coding-agent</a></p>

## Installation

1) Install pi:
```bash
npm install -g @mariozechner/pi-coding-agent
```

2) Install uv:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

3) Install pipal (recommended):
```bash
uv tool install git+https://github.com/mohammadbashiri/pipal.git
```

For local development (editable install):
```bash
git clone https://github.com/mohammadbashiri/pipal
cd pipal
uv tool install -e .
```

If you update dependencies in `pyproject.toml`, reinstall the tool env:
```bash
uv tool uninstall pipal
uv tool install -e .
```

## Quick Start

```bash
pipal agent create momo
pipal agent chat momo
```

## Agent types

pipal supports multiple agent types (different templates and behaviors). See [agent_types.md](agent_types.md).
<---

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

Existing registries in `~/.pi/agents.json` are auto‑migrated on first run.

## Uninstall

Run the interactive uninstaller (choose which components to remove):
```bash
pipal uninstall
```

It will optionally remove:
- the local pipal data directory (`~/.pipal`)
- the pipal CLI (`uv tool uninstall pipal`)

## Tasks (coming soon)

`src/pipal/templates/default/task.md` is the template that will be used when task support lands.

## Notes

- pipal depends on pi for models, login, and tool execution.
- If no models are available, run `pi` and complete `/login` first.
