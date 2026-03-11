# pal

Persistent agents on top of [pi](https://github.com/badlogic/pi-mono).

## Install

1) Install pi:
```bash
npm install -g @mariozechner/pi-coding-agent
```

2) Install pal (editable for dev):
```bash
uv tool install -e .
```

## Quick Start

```bash
pal agent create momo
pal agent chat momo
```

On create, pal will prompt you to pick a model from `pi --list-models` and write `llm.json`.

## Storage

By default, agents are created under:
```
~/.pal/agents/<agent_name>
```

Registry:
```
~/.pal/agents.json
```

Pass a custom base path to override the default:
```
pal agent create momo /path/to/agents
```

Existing registries in `~/.pi/agents.json` are auto‑migrated on first run.

## Tasks (coming soon)

`src/pi_agents/templates/default/task.md` is the template that will be used when task support lands.

## Notes

- pal depends on pi for models, login, and tool execution.
- If no models are available, run `pi` and complete `/login` first.
