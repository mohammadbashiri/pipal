# Topics and pi sessions

Pipal uses **topic** and **session** for two distinct levels of continuity:

- A **topic** is a named Pipal container owned by an agent.
- A **session** is a native pi JSONL conversation tree inside a topic.

One topic can span many pi sessions. Its rolling summary and recent-session context let the agent continue across separate launches.

## Storage

```text
~/.pipal/agents/<agent>/topics/<topic>/
├── summary.md
├── summary.log
├── summary.state.json
├── topic.json
└── sessions/
    ├── <timestamp>_<uuid>.jsonl
    └── <timestamp>_<uuid>.jsonl
```

`topic.json` contains title and timestamp metadata used by the optional server. Each `.jsonl` file remains a native pi session, including pi's in-file tree, compactions, and session ID.

Older Pipal layouts under `sessions/<topic>/` are migrated automatically and non-destructively when an agent's topics are first accessed.

## Starting and continuing chats

```bash
# Start a fresh pi session in the default "main" topic
pipal agent chat momo

# Start a fresh pi session in a named topic
pipal agent chat momo --topic work

# Continue the latest pi session in that topic
pipal agent chat momo --topic work --continue

# Open pi's session picker, scoped to the topic
pipal agent chat momo --topic work --resume
```

Pipal consumes `--topic`; native pi session flags such as `--session`, `--continue`, and `--resume` are passed to pi.

## Topic commands

```bash
pipal topic list --agent momo
pipal topic summarize --agent momo --topic work
pipal topic remove --agent momo --topic work
```

Removing a topic removes its rolling summary, metadata, and all contained pi sessions.

## Native pi session commands

```bash
pipal session list --agent momo --topic work
pipal session info <filename-or-id> --agent momo --topic work
pipal session open <filename-or-id> --agent momo --topic work
pipal session remove <filename-or-id> --agent momo --topic work
```

A session can be selected by filename, absolute path within the topic, filename prefix, or unique pi session-ID prefix.

## Server API

The optional server mirrors the hierarchy:

```text
GET  /agents/{agent}/topics
POST /agents/{agent}/topics
GET  /agents/{agent}/topics/{topic}/history
GET  /agents/{agent}/topics/{topic}/sessions
GET  /agents/{agent}/topics/{topic}/sessions/{session}/history
```

WebSocket initialization uses:

```json
{
  "type": "init",
  "agent": "momo",
  "topic": "work",
  "session": "optional-existing-session.jsonl"
}
```

Omit `session` to create a new native pi session inside the topic.
