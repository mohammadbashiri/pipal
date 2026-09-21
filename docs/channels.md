# Pipal channels

A channel is a durable shared room for a human and any registered Pipal agents. Agents are participants, not child processes of a manager. The shared conversation is the coordination surface.

## Create and open a channel

```bash
pipal channel create product \
  --member momolty:Builder \
  --member code-reviewer:Reviewer \
  --owner "Dr Mo"

pipal channel chat product --topic v1
```

Inside the room, mention an agent to ask it to respond or work:

```text
@momolty sketch the smallest useful implementation.
@code-reviewer challenge that proposal.
@channel assess both options.
```

Messages without an agent mention are recorded in the shared channel conversation but do not automatically run an agent. This keeps ordinary human discussion calm and makes agent activation explicit.

## Model

A channel has:

- a human owner;
- a flat roster of registered agent participants;
- an append-only, attributed shared transcript;
- one private native Pi session per agent per channel topic.

The transcript is the canonical visible channel history. Each agent keeps private working context in its own Pi session, and reads the shared transcript only when relevant context is required. Agent messages, visible tool activity, timeouts, and warnings are all recorded as channel events.

## Storage

```text
~/.pipal/channels/<channel>/
├── channel.json
└── topics/<topic>/
    ├── transcript.jsonl
    ├── runtime.json
    ├── runtime-prompts/
    └── members/<agent>/sessions/
```

Channels deliberately do not impose a manager or a topology. Mention routing is the only activation mechanism: `@agent` routes to one participant, while `@channel` and `@all` fan out to all participants. `@team` remains a compatibility alias.
