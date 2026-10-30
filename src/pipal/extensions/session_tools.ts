import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

interface LiveSession {
  session_id: string;
  agent?: string;
  topic?: string;
  name?: string;
  [key: string]: unknown;
}
interface Request {
  request_id: string;
  session_id: string;
  status: string;
  reply?: unknown;
  error?: string;
}
interface Pending { target: string; request_id: string }
const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const waitSchema = Type.Optional(Type.Number({ minimum: 0, maximum: 30, description: "Wait seconds (0–30); default 0. Pending requests can be retrieved later." }));

/** No delivery retry: only read-only list/result calls run in the background. */
export default function sessionTools(pi: ExtensionAPI) {
  let generation = 0;
  let active: ExtensionContext | undefined;
  let controller = new AbortController();
  let timer: ReturnType<typeof setInterval> | undefined;
  let sessions: LiveSession[] = [];
  let nextRefresh = 0;
  let polling = false;
  const pending = new Map<string, Pending>();
  const key = (p: Pending) => `${p.target}/${p.request_id}`;
  const current = (ctx: ExtensionContext, epoch: number, id: string) =>
    generation === epoch && !controller.signal.aborted && ctx.sessionManager.getSessionId() === id;

  async function cli(args: string[], signal?: AbortSignal): Promise<any> {
    const waitIndex = args.indexOf("--wait");
    const wait = waitIndex < 0 ? 0 : Number(args[waitIndex + 1]);
    if (!Number.isFinite(wait) || wait < 0 || wait > 30) throw new Error("wait must be between 0 and 30 seconds");
    const timeout = args[0] === "start" ? 35000 : Math.max(5000, wait * 1000 + 5000);
    const result = await pi.exec("pipal", ["live", ...args, "--json"], { signal, timeout });
    let value: any;
    try { value = JSON.parse(result.stdout); }
    catch { throw new Error(`pipal live ${args[0]}: invalid JSON response (exit ${result.code})`); }
    if (result.code !== 0 || value?.error) throw new Error(`${value?.error || `pipal live ${args[0]} failed (exit ${result.code})`}${value?.request_id ? ` · request ${value.request_id}` : ""}`);
    if (!value || typeof value !== "object") throw new Error("Invalid live-session response");
    return value;
  }
  const output = (value: any) => ({ content: [{ type: "text" as const, text: JSON.stringify(value) }], details: value });
  function remember(value: any, ctx: ExtensionContext, epoch: number, id: string) {
    const request = value?.request as Request | undefined;
    if (!request?.request_id || !request.session_id || !current(ctx, epoch, id)) return;
    const p = { target: request.session_id, request_id: request.request_id };
    pi.appendEntry("pipal-session-request", { ...p, source_session_id: id, status: request.status });
    if (terminal.has(request.status)) pending.delete(key(p));
    else pending.set(key(p), p);
  }
  function visible(customType: string, content: string, details: { request_id: string; session_id: string; status: string }, sourceId: string) {
    const message = { customType, content, display: true, details };
    pi.sendMessage(message, { triggerTurn: false });
    try {
      pi.events.emit("pipal:session-visible", {
        session_id: sourceId,
        message: { role: "custom", ...message, timestamp: Date.now() },
      });
    } catch { /* Optional observers must not alter delivery or result state. */ }
  }
  function display(request: Request, sourceId: string) {
    const session = sessions.find(s => s.session_id === request.session_id);
    const attribution = [session?.kind === "pi" ? "Pi" : session?.agent, session?.topic, session?.name || (session?.kind === "pi" ? session.directory : "")].filter(Boolean).join(" / ");
    const reply = typeof request.reply === "string" ? request.reply : JSON.stringify(request.reply ?? "");
    visible("pipal-session-display",
      `@session:${request.session_id}${attribution ? ` (${attribution})` : ""} · ${request.request_id} · ${request.status}\n${request.error || reply || "(no reply)"}`,
      { request_id: request.request_id, session_id: request.session_id, status: request.status }, sourceId);
  }
  function displayError(target: string, requestId: string, error: unknown, sourceId: string) {
    visible("pipal-session-display",
      `@session:${target} · request ${requestId} · error\n${String(error)}\nNot retried. Use pipal_session_result to check this request.`,
      { request_id: requestId, session_id: target, status: "failed" }, sourceId);
  }
  for (const type of ["pipal-session-outbound", "pipal-session-display"]) {
    pi.registerMessageRenderer(type, message => new Text(String(message.content), 1, 0));
  }

  async function poll(ctx: ExtensionContext, epoch: number, id: string) {
    if (polling || !current(ctx, epoch, id)) return;
    polling = true;
    const signal = controller.signal;
    try {
      if (Date.now() >= nextRefresh) {
        nextRefresh = Date.now() + 10000;
        try {
          const value = await cli(["list"], signal);
          if (current(ctx, epoch, id) && Array.isArray(value.sessions)) sessions = value.sessions.filter((s: LiveSession) => s && uuid.test(s.session_id)).slice(0, 500);
        } catch { /* Discovery is best effort; never touch credentials or runtime files. */ }
      }
      for (const p of [...pending.values()].slice(0, 64)) {
        if (!current(ctx, epoch, id)) return;
        try {
          const value = await cli(["result", p.target, p.request_id, "--wait", "0"], signal);
          if (!current(ctx, epoch, id)) return;
          if (value.request?.request_id !== p.request_id || value.request?.session_id !== p.target) throw new Error("Mismatched result identity");
          if (!pending.has(key(p))) continue; // A foreground result may already have consumed it.
          if (terminal.has(value.request.status)) {
            remember(value, ctx, epoch, id);
            display(value.request, id);
          } else {
            // Round-robin bounded batches so a long-running request cannot starve newer ones.
            pending.delete(key(p));
            pending.set(key(p), p);
          }
        } catch (error) {
          if (!current(ctx, epoch, id)) return;
          // Stop automatic retrieval on failure, but keep the durable request ID for manual retrieval.
          pending.delete(key(p));
          displayError(p.target, p.request_id, error, id);
          ctx.ui.notify(`Session result ${p.target} / ${p.request_id}: ${String(error)}. Retrieve with pipal_session_result.`, "warning");
        }
      }
    } finally { if (generation === epoch) polling = false; }
  }

  const target = Type.String({ description: "Full native UUID, unique UUID prefix, or @session:UUID (not an agent name)." });
  const register = (name: string, description: string, parameters: any, args: (p: any, ctx: ExtensionContext, signal: AbortSignal) => string[] | Promise<string[]>) => {
    pi.registerTool({
      name, label: name.replace("pipal_session_", "Session "), description, parameters,
      async execute(_call, params, signal, _update, ctx) {
        const epoch = generation, id = ctx.sessionManager.getSessionId();
        const deliverySignal = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
        const argv = await args(params, ctx, deliverySignal);
        if (!current(ctx, epoch, id) || deliverySignal.aborted) throw new Error("Source session changed or delivery was cancelled");
        const value = await cli(argv, deliverySignal);
        remember(value, ctx, epoch, id);
        return output(value);
      },
    });
  };
  const sender = (ctx: ExtensionContext) => ["--sender-session", ctx.sessionManager.getSessionId()];
  register("pipal_session_list", "Discover live native sessions and attach commands, or inspect one target. Saved conversations are not live sessions.", Type.Object({ session: Type.Optional(target) }), p => p.session ? ["inspect", p.session] : ["list"]);
  register("pipal_session_start", "Start a detached Pi or Pipal native TUI (or safely resume a saved conversation). Pi has no Pipal identity, topic or memory. Does not change model defaults. An initial message returns a retrievable request ID.", Type.Object({
    kind: Type.Optional(Type.Union([Type.Literal("pi"), Type.Literal("pipal")], { description: "Default pipal for compatibility. Choose pi for a plain native conversation." })),
    agent: Type.Optional(Type.String({ description: "Required for pipal; omit for pi" })), topic: Type.Optional(Type.String({ description: "Pipal topic only; default main" })), directory: Type.String(),
    session: Type.Optional(Type.String({ description: "Saved conversation reference to resume safely" })),
    model: Type.Optional(Type.String()), provider: Type.Optional(Type.String()),
    text: Type.Optional(Type.String({ description: "Optional initial message" })),
  }), (p, ctx) => {
    if (p.provider && !p.model) throw new Error("provider requires model");
    const kind = p.kind ?? "pipal";
    if (kind !== "pi" && kind !== "pipal") throw new Error("kind must be pi or pipal");
    if (kind === "pipal" && !p.agent) throw new Error("Pipal sessions require an agent");
    if (kind === "pi" && (p.agent || p.topic)) throw new Error("Plain Pi sessions do not have a Pipal agent or topic");
    const args = ["start", ...(p.kind ? ["--kind", kind] : []), ...(p.agent ? ["--agent", p.agent] : []), ...(p.topic ? ["--topic", p.topic] : []), "--directory", p.directory, ...sender(ctx)];
    for (const flag of ["session", "model", "provider"]) if (p[flag] !== undefined) args.push(`--${flag}`, p[flag]);
    if (p.text !== undefined) args.push(`--text=${p.text}`);
    return args;
  });
  register("pipal_session_message", "Send once to a live native session. Busy sessions queue messages; pending request IDs are retained. No delivery retries; use result to retrieve a reply.", Type.Object({ target, text: Type.String(), wait: waitSchema, request_id: Type.Optional(Type.String({ format: "uuid", description: "Optional idempotency UUID; generated once if omitted. Never retry delivery automatically." })) }), (p, ctx) => ["message", p.target, `--text=${p.text}`, ...sender(ctx), "--request-id", p.request_id ?? randomUUID(), "--wait", String(p.wait ?? 0)]);
  register("pipal_session_result", "Retrieve a previous request without retransmitting or triggering a source model turn.", Type.Object({ target, request_id: Type.String(), wait: waitSchema }), p => ["result", p.target, p.request_id, "--wait", String(p.wait ?? 0)]);
  register("pipal_session_quit", "Gracefully quit an idle live session. Refuses busy/queued sessions; no force quit or arbitrary terminal control.", Type.Object({ target, confirm_unmanaged: Type.Optional(Type.Boolean({ description: "Default false. Request explicit owner confirmation in the original TUI for sessions not created by this source. On phone-only App use, the owner can instead use that target chat's Quit control. Never bypass approval." })) }), async (p, ctx, signal) => {
    const args = ["quit", p.target, ...sender(ctx)];
    if (p.confirm_unmanaged) {
      if (!ctx.hasUI || !(await ctx.ui.confirm("Quit another session?", `Explicitly approve gracefully quitting ${p.target}, which may not have been created by this source?`, { signal, timeout: 60000 }))) throw new Error("Owner approval required to quit an unmanaged session");
      args.push("--confirm-unmanaged");
    }
    return args;
  });

  pi.on("input", (event, ctx) => {
    const match = /^\s*@session:([0-9a-f-]+)(?:\s+([\s\S]*))?$/i.exec(event.text);
    if (!match) return { action: "continue" };
    // Consume direct addresses before delegation's @agent/@team routing; inner mentions are payload.
    if (event.images?.length || !match[2]?.trim()) {
      ctx.ui.notify("Usage: @session:<UUID or unique prefix> <text> (text only)", "warning");
      return { action: "handled" };
    }
    const epoch = generation, id = ctx.sessionManager.getSessionId();
    const signal = controller.signal;
    const requestId = randomUUID();
    visible("pipal-session-outbound", `To @session:${match[1]} · request ${requestId}:\n${match[2]}`,
      { request_id: requestId, session_id: match[1], status: "queued" }, id);
    // Do not await delivery/polling on the editor submission path.
    void cli(["message", match[1], `--text=${match[2]}`, ...sender(ctx), "--request-id", requestId, "--wait", "0"], signal).then(value => {
      if (!current(ctx, epoch, id)) return;
      remember(value, ctx, epoch, id);
      if (terminal.has(value.request?.status)) display(value.request, id);
      else ctx.ui.notify(`Queued @session:${value.request?.session_id} · request ${value.request?.request_id}`, "info");
    }).catch(error => {
      if (!current(ctx, epoch, id)) return;
      displayError(match[1], requestId, error, id);
      ctx.ui.notify(`Session delivery failed (not retried); target ${match[1]}, request ${requestId}: ${String(error)}. Use pipal_session_result to check delivery.`, "error");
    });
    return { action: "handled" };
  });

  function stop() {
    generation++;
    controller.abort();
    if (timer) clearInterval(timer);
    timer = undefined;
    active = undefined;
    pending.clear();
    sessions = [];
    polling = false;
  }
  pi.on("session_shutdown", stop);
  function startContext(ctx: ExtensionContext, addAutocomplete = true) {
    stop();
    controller = new AbortController();
    active = ctx;
    const epoch = generation, id = ctx.sessionManager.getSessionId();
    for (const entry of ctx.sessionManager.getBranch()) {
      if (entry.type !== "custom" || entry.customType !== "pipal-session-request") continue;
      const data = entry.data as Pending & { status: string; source_session_id?: string };
      if (!data?.target || !data.request_id || data.source_session_id !== id) continue;
      if (terminal.has(data.status)) pending.delete(key(data)); else pending.set(key(data), data);
    }
    nextRefresh = 0;
    void poll(ctx, epoch, id);
    timer = setInterval(() => { void poll(ctx, epoch, id); }, 1500);
    timer.unref?.();
    if (!addAutocomplete || ctx.mode !== "tui") return;
    ctx.ui.addAutocompleteProvider(currentProvider => ({
      triggerCharacters: ["@"],
      async getSuggestions(lines, line, col, options) {
        const match = /(?:^|\s)@session:([\w.-]*)$/i.exec((lines[line] ?? "").slice(0, col));
        if (!match) return currentProvider.getSuggestions(lines, line, col, options);
        if (!active || options.signal.aborted) return null;
        const query = match[1].toLowerCase();
        const items = sessions.filter(s => s.session_id !== active!.sessionManager.getSessionId()).filter(s => [s.session_id, s.agent, s.topic, s.name, s.directory, s.kind].some(v => String(v ?? "").toLowerCase().includes(query))).slice(0, 100).map(s => ({
          value: `@session:${s.session_id}`,
          label: [s.kind === "pi" ? "Pi" : s.agent, s.topic, s.name || (s.kind === "pi" ? s.directory : "")].filter(Boolean).join(" / ") || s.session_id,
          description: `@session:${s.session_id}`,
        }));
        return items.length ? { prefix: `@session:${match[1]}`, items } : null;
      },
      applyCompletion: (lines, line, col, item, prefix) => currentProvider.applyCompletion(lines, line, col, item, prefix),
      shouldTriggerFileCompletion: (lines, line, col) => currentProvider.shouldTriggerFileCompletion?.(lines, line, col) ?? true,
    }));
  }
  pi.on("session_start", (_event, ctx) => startContext(ctx));
  // Tree navigation keeps the UUID but changes the branch receiving replies.
  pi.on("session_tree", (_event, ctx) => startContext(ctx, false));
}
