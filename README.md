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
pal agent create momo ./agents
pal agent chat momo
```

On create, pal will prompt you to pick a model from `pi --list-models` and write `llm.json`.

## Storage

By default, pal stores its registry in:
```
~/.pal/agents.json
```

Existing registries in `~/.pi/agents.json` are auto‑migrated on first run.

## Notes

- pal depends on pi for models, login, and tool execution.
- If no models are available, run `pi` and complete `/login` first.
