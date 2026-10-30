# Live Pi and Pipal sessions

Participating Pi and Pipal sessions can discover, start, communicate with, and gracefully quit other live sessions (Pi 1.4.0 or newer). This works without Pi App or Telegram. Pi remains the sole runtime and writer for each native conversation.

## Addressing

A session's **native Pi UUID** is its stable conversation identity, including after closing and resuming. A **runtime UUID** identifies the particular live process/connection. Agent, topic and native session name are readable labels, not addresses: two sessions may have identical labels.

Use `@session:<full-native-UUID>` for an unambiguous mention. The CLI also accepts unique UUID prefixes of at least eight characters; ambiguous prefixes are rejected, never guessed. Use full IDs to retrieve results after a recipient exits.

## Agent tools

- `pipal_session_list`: discover running sessions, or inspect a target.
- `pipal_session_start`: choose `kind: "pi"` for a plain native conversation, or `kind: "pipal"` (the backward-compatible default) with a registered agent and optional topic. Both support a directory, closed-conversation resume and initial work. Plain Pi rejects agent/topic fields and receives no Pipal persona, memory or summary command. Returns the session identity and handoff command.
- `pipal_session_message`: send once; receive a durable request ID. `wait` can wait up to 30 seconds for the result.
- `pipal_session_result`: inspect or wait for the existing request without retransmission.
- `pipal_session_quit`: quit gracefully if idle. It never interrupts active/queued work or force-kills a runtime.

Agents can create a conversation, get work started and leave it for a human, without making it a delegation. Existing delegation remains available for its dedicated ownership, review and reporting lifecycle; this first slice does not migrate existing delegation storage to live-session primitives.

## Human use

In any participating TUI, type `@session:` to select a running session. A leading mention followed by text sends directly to that session and displays an attributed reply without calling the source model. Mentions elsewhere in a normal prompt are references for the source agent to interpret. Direct messages are text-only; attach files through the normal conversation or ask the agent to share explicit paths when appropriate.

Pi App offers the same mixed Pi/Pipal session picker when typing `@` in either chat type. Pi sessions show their native name/directory instead of agent/topic. It inserts the same full native reference; ordinary native input hooks handle delivery. Older source sessions must `/reload` before direct mentions are enabled. The picker is not another registry or messaging service.

CLI equivalents (JSON output):

```sh
pipal live list --json
pipal live inspect <session-id> --json
pipal live start --agent my-agent --topic work --directory /path/to/project --json
pipal live start --kind pi --directory /path/to/project --json
pipal live message <session-id> --text='What is your current status?' --json
pipal live result <session-id> <request-id> --wait 30 --json
pipal live attach <session-id>
pipal live quit <session-id> --json
```

Use `--session <saved-file-or-id>` on Pipal `start` to resume a closed conversation in the selected agent/topic. Plain Pi uses `--kind pi --session /explicit/native-session.jsonl`; it does not search or adopt Pipal topics. Running conversations must be contacted, not opened with another writer. Explicit `--provider`/`--model` affect that launch only; Pi owns defaults and authentication. Started sessions suppress the automatic greeting so merely creating an empty handoff session does not make a model call.

Agent tools supply `--sender-session` from the actual source runtime. A local CLI invocation without a sender represents the owner. An agent may close an idle session it created; closing any other session requires explicit owner approval (`confirm_unmanaged` in the tool, `--confirm-unmanaged` in the CLI). The tool's approval dialog appears in the original TUI and can be cancelled; phone-only owners can instead use the existing Quit control in the target App chat. Self-quit remains native `/quit`. This is a trusted single-user workspace, not a multi-tenant authorization boundary: all these processes already have the owner's local shell privileges.

## Delivery and results

A queued acknowledgement is **not** a completed answer. Incoming requests wait until the recipient is idle, with no pending native messages or compaction. They never interrupt or steer existing work. The receiver sees sender identity and request ID; its ordinary visible answer becomes the reply automatically. It should not start a separate message back just to deliver that answer.

Requests progress through `queued`, `running`, and `completed`/`failed`. Reload or shutdown marks undelivered work `cancelled` and interrupted work `interrupted`. After a crash, an unavailable runtime makes pending delivery/result uncertain. Nothing is automatically replayed on resume. Check the existing request ID rather than blindly resending.

Request IDs provide idempotency: submitting identical content under the same ID does not deliver it twice; changing the content/sender under that ID is rejected. No client performs automatic delivery retries. Result retrieval is read-only and can be repeated. Completed results survive recipient shutdown. Passive replies do not automatically trigger a source agent/model turn. Native history retains normal tool results and visible session messages; source bookkeeping is scoped to its native UUID so a different fork does not inherit pending reply delivery.

If startup succeeds but the optional initial message fails, the start result still returns the created session and `initial_message_error`, rather than hiding a live conversation and inviting a duplicate start.

## Local runtime and handoff

The shared `extensions/session_bridge.ts` extension registers an owner-only Unix socket and presence record under the configured Pipal home. Pipal's command entry point loads it automatically. Plain Pi opts in by loading that extension (globally or with `pi --extension <path>/session_bridge.ts`); the local install enables it globally. Loading it globally and through Pipal/explicit flags still initializes exactly once per runtime. Its stable extension entry point lets existing Pipal TUIs gain the feature through `/reload`; no owner session is reloaded automatically.

```text
<PIPAL_HOME>/runtime/
  sessions/<native-UUID>.json
  messages/<native-UUID>/<request-UUID>.json
```

Records are mode `0600` in owner-only directories. Live probes validate both conversation and runtime UUIDs rather than trusting PIDs. Stale entries do not count as running sessions. Socket files live in a short, owner-only `/tmp/pipal-live-<uid>-<home-hash>/` directory to respect macOS Unix-socket path limits. Symlink/insecure runtime records are rejected. Message/result records are retained locally; they contain conversation text, so treat them as private history and remove them manually when no longer needed.

Agent-started sessions use a **Pipal-owned private tmux server**, not Pi App's server or the owner's default tmux socket. `pipal live attach` attaches to that same native process. Detach normally to leave it running; a human can continue the existing conversation without a second writer. Plain TUI-origin sessions stay in their original terminal and do not acquire a synthetic mirrored terminal.

Pi App remains an optional consumer: the existing App extension supplies its Chat/Voice view, while discovery and session communication belong to Pipal. The App's own existing start/quit controls remain available. Only runtimes with the communication extension loaded participate. Existing Pi/Pipal processes need an owner-initiated `/reload`; they are never automatically claimed, reloaded or taken over. Registry records expose `kind: "pi" | "pipal"`, while native UUID addressing and queue/approval safeguards are shared. A plain Pi launch strips inherited Pipal identity/delegation flags, invokes the normal Pi CLI, and takes the same advisory resume lock before exec; Pipal persona/topic context is never injected.
