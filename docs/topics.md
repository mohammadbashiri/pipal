# Topics and pi sessions

Pipal uses **topic** and **session** for two distinct levels of continuity:

- A **topic** is a named Pipal container owned by an agent.
- A **session** is a native pi JSONL conversation tree inside a topic.

One topic can span many Pi sessions. Native history is authoritative; an optional, agent-maintained summary is a compact reference for continuity across launches. Neither summary text nor previous-session messages are loaded automatically.

## Storage

```text
~/.pipal/agents/<agent>/topics/<topic>/
├── summary.md             # optional, edited by the agent with your agreement
├── topic.json
└── sessions/
    ├── <timestamp>_<uuid>.jsonl
    └── <timestamp>_<uuid>.jsonl
```

`/pipal:summary` asks the agent for a summary of the current conversation in chat, optionally focused by words after the command. It does not save, compact, or exit. The agent may naturally discuss keeping a useful summary; saving is normal file editing with your agreement. There is no scripted save prompt. Saved entries should identify the source session and covered branch entry ID or timestamp, not mark an entire resumable session permanently summarized.

Agents are told where to find this file and native sessions, and consult them on demand. Missing summaries are normal: use session history instead. Existing `summary.log` and `summary.state.json` files remain untouched as legacy artifacts, not current coverage indexes. The old automatic summarizer and `pipal topic summarize` CLI have been removed. Native `/compact` is unchanged and `/quit` just quits.

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
pipal topic remove --agent momo --topic work
```

Removing a topic removes its optional summary, metadata, and all contained Pi sessions.

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
