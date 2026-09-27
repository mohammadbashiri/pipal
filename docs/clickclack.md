# ClickClack integration

The optional ClickClack bridge connects ClickClack bot users to locally registered Pipal agents. Run it on the same trusted machine that holds the agents and their provider configuration. When someone mentions a mapped bot in ClickClack, the bridge sends that agent the recent channel context and posts its reply back as that bot.

This is alpha, local-first tooling. The bridge runs agents with your local user permissions and its configuration contains bearer tokens. Do not expose the bridge, its configuration, or its state file to untrusted users or networks.

## Prerequisites

- Pipal and Pi are installed and `pipal check-pi-compatibility` succeeds.
- Each agent that will answer in ClickClack is registered locally and has a working LLM configuration. Verify with `pipal agent list` and, if needed, `pipal agent chat <agent>`.
- A ClickClack workspace and one bot user for every mapped Pipal agent.
- A bearer token for each bot user. It must be able to receive workspace realtime events and read and post channel messages.

## Configure the bridge

Create `~/.pipal/integrations/clickclack.json` with the ClickClack server URL, workspace ID, and one mapping per bot:

```json
{
  "base_url": "http://127.0.0.1:3000",
  "workspace_id": "workspace-id",
  "agents": [
    {
      "agent": "momo",
      "handle": "momo",
      "bot_user_id": "clickclack-bot-user-id",
      "token": "clickclack-bot-bearer-token"
    }
  ]
}
```

`agent` must exactly match a locally registered Pipal agent. `handle` is the bot's ClickClack handle, used in the prompt supplied to the agent. `bot_user_id` and `token` belong to that ClickClack bot user. Add another object to `agents` for each additional bot.

Keep this file private—for example, set its permissions to owner-only:

```bash
chmod 600 ~/.pipal/integrations/clickclack.json
```

## Run it

```bash
pipal integration clickclack run
```

Use `--config /path/to/clickclack.json` for a different configuration path. Keep the process running (for example through a local process supervisor) while you want the integration active. The bridge saves its realtime cursor beside the configuration as `clickclack.state.json`; deleting that file makes the next start begin at the current event tail, not replay old messages.

## Use it in ClickClack

Mention a mapped bot by its ClickClack handle to activate only that agent. The bridge includes the triggering message and up to twelve recent channel messages in the prompt, then posts the agent's response into the same channel. A bot does not respond to its own messages.

`@all` and `@channel` are bridge conveniences: including either in a message sends it to every mapped bot. They are text-based fan-out triggers, so use them only when you want every agent to respond.

## Troubleshooting

- **“mapped Pipal agent is unavailable”**: the configured `agent` is not registered locally or has no usable LLM configuration.
- **The bridge reconnects repeatedly**: verify `base_url`, `workspace_id`, network reachability, and the bot token's realtime-event permission.
- **A bot does not answer**: confirm its ClickClack user was mentioned, its `bot_user_id` matches the mapping, and its token can read and post in that channel.
