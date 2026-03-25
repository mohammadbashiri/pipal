# Agent types

pipal supports **agent types**, which let you scaffold agents with different default behaviors, templates, and configuration.

## Available types

- **default** — the standard pipal agent template (general‑purpose assistant).
- **kbchat** — a knowledge‑base agent that is wired to a local KB path for grounded Q&A.

> You can add more types by creating new templates in the templates directory (see “How types work”).

## Create an agent with a specific type

```bash
pipal agent create <name> --type <type>
```

Examples:

```bash
# Default type (explicit)
pipal agent create momo --type default

# KB chat type
pipal agent create erwin --type kbchat --kb /tmp/knowledge_base
```

## How types work (behind the scenes)

Agent types are implemented as **template folders**. Each type defines a set of “core files” that are copied into the agent’s home directory at creation time.

- Templates live under:
  - `src/pipal/templates/<type>/`
- Core files include:
  - `AGENTS.md`, `IDENTITY.md`, `POLICY.md`, `USER.md`, `MEMORY.md`, `JOURNAL.md`
  - type‑specific files (e.g. `KB.md` for kbchat)

When you run `pipal agent create`, pipal selects the template folder for the given `--type` and copies those files into:

```
~/.pipal/agents/<agent_name>/
```

For **kbchat**, the `--kb` flag is used to populate the KB path, which is written into:

```
~/.pipal/agents/<agent_name>/KB.md
```

## KB Chat (Erklär‑Erwin)

Create a knowledge‑base agent (kbchat):

```bash
pipal agent create erwin --type kbchat --kb /tmp/knowledge_base
```

This writes the KB path into:

```
~/.pipal/agents/erwin/KB.md
```
