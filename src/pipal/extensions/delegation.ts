import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  CustomEditor,
  createBashToolDefinition,
  createEditToolDefinition,
  createFindToolDefinition,
  createGrepToolDefinition,
  createLsToolDefinition,
  createReadToolDefinition,
  createWriteToolDefinition,
  getMarkdownTheme,
} from "@earendil-works/pi-coding-agent";
import { Box, Container, Loader, Markdown, Spacer, Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

interface DelegateRuntime {
  agent: string;
  role: string;
  agent_path: string;
  provider?: string;
  model?: string;
  prompt_file: string;
  session_file: string;
  transcript_file: string;
}

interface TeamRuntime {
  name: string;
  manager?: string;
  members: Array<{ agent: string; role?: string }>;
}

interface DelegationRuntime {
  primary: string;
  primary_path: string;
  topic: string;
  working_dir: string;
  native_pi: string;
  agent_timeout_seconds?: number;
  max_turns?: number;
  background_root?: string;
  worker_python?: string;
  delegates: DelegateRuntime[];
  teams?: TeamRuntime[];
}

interface ToolRun {
  id: string;
  name: string;
  args: any;
  result?: any;
  isError?: boolean;
  status: "running" | "done" | "failed";
}

interface BackgroundResult {
  background: true;
  job_id: string;
  agent: string;
  status: string;
}

interface DelegateResult {
  agent: string;
  delegationId?: string;
  role: string;
  model?: string;
  text: string;
  inputTokens: number;
  outputTokens: number;
  cost: number;
  status: string;
  tools: ToolRun[];
}

interface TeamDelegateResult {
  team: string;
  delegation_id: string;
  background: boolean;
  results: DelegateResult[];
  jobs?: BackgroundResult[];
}

class CompactLoader extends Loader {
  override render(width: number): string[] {
    const lines = super.render(width);
    return lines[0] === "" ? lines.slice(1) : lines;
  }
}

class DelegationEditor extends CustomEditor {
  constructor(
    tui: any,
    theme: any,
    private delegationKeybindings: any,
    private knownAgents: Set<string>,
    private knownTeams: Set<string>,
    private cancelDirect: () => boolean,
  ) {
    super(tui, theme, delegationKeybindings);
  }

  override handleInput(data: string): void {
    if (
      this.delegationKeybindings.matches(data, "app.interrupt")
      && !this.isShowingAutocomplete()
      && this.cancelDirect()
    ) return;

    if (this.delegationKeybindings.matches(data, "tui.input.submit") && !this.isShowingAutocomplete()) {
      const text = this.getExpandedText();
      let escaped = text.replace(/@agent:([\w.-]+)/g, (value, name) =>
        this.knownAgents.has(String(name).toLowerCase()) ? `\\${value}` : value);
      escaped = escaped.replace(/@team(?::([\w.-]+))?/g, (value, name) =>
        !name || this.knownTeams.has(String(name).toLowerCase()) ? `\\${value}` : value);
      if (escaped !== text) this.setText(escaped);
    }
    super.handleInput(data);
  }
}

function loadRuntime(): DelegationRuntime | null {
  const path = process.env.PIPAL_DELEGATION_RUNTIME;
  if (!path) return null;
  try {
    return JSON.parse(fs.readFileSync(path, "utf8")) as DelegationRuntime;
  } catch {
    return null;
  }
}

function appendEvent(delegate: DelegateRuntime, event: Record<string, unknown>): void {
  fs.appendFileSync(delegate.transcript_file, `${JSON.stringify({
    schema_version: 1,
    id: randomUUID(),
    timestamp: new Date().toISOString(),
    ...event,
  })}\n`, "utf8");
}

function resultText(result: any): string {
  return Array.isArray(result?.content)
    ? result.content.filter((part: any) => part?.type === "text").map((part: any) => part.text).join("\n")
    : "";
}

function assistantText(message: any): string {
  return message?.role === "assistant" && Array.isArray(message.content)
    ? message.content.filter((part: any) => part?.type === "text").map((part: any) => part.text).join("\n").trim()
    : "";
}

function stripPrefix(text: string, agent: string): string {
  const escaped = agent.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text.replace(new RegExp(`^@?(?:agent:)?${escaped}(?:\\s*\\([^)]*\\))?\\s*:\\s*`, "i"), "");
}

function startBackgroundJob(
  runtime: DelegationRuntime,
  delegate: DelegateRuntime,
  message: string,
  acceptanceCriteria?: string,
  options?: { delegationId?: string; team?: string },
): BackgroundResult {
  if (!runtime.background_root || !runtime.worker_python) {
    throw new Error("Background delegation is unavailable in this runtime");
  }
  const jobId = `dg-${randomUUID().slice(0, 8)}`;
  const delegationId = options?.delegationId ?? jobId;
  const jobDir = `${runtime.background_root}/${jobId}`;
  fs.mkdirSync(jobDir, { recursive: true });
  const sessionFile = `${jobDir}/session.jsonl`;
  if (fs.existsSync(delegate.session_file)) {
    const lines = fs.readFileSync(delegate.session_file, "utf8").split("\n").filter(Boolean);
    const header = {
      type: "session",
      version: 3,
      id: randomUUID(),
      timestamp: new Date().toISOString(),
      cwd: runtime.working_dir,
      parentSession: delegate.session_file,
    };
    fs.writeFileSync(sessionFile, `${[JSON.stringify(header), ...lines.slice(1)].join("\n")}\n`, "utf8");
  }
  const jobFile = `${jobDir}/job.json`;
  fs.writeFileSync(jobFile, `${JSON.stringify({
    schema_version: 1,
    id: jobId,
    delegation_id: delegationId,
    team: options?.team,
    status: "queued",
    created_at: new Date().toISOString(),
    primary: runtime.primary,
    topic: runtime.topic,
    working_dir: runtime.working_dir,
    native_pi: runtime.native_pi,
    timeout_seconds: runtime.agent_timeout_seconds ?? 300,
    delegate,
    message,
    acceptance_criteria: acceptanceCriteria,
    session_file: sessionFile,
    reported: false,
  }, null, 2)}\n`, "utf8");
  const worker = spawn(runtime.worker_python, ["-m", "pipal.delegation_worker", jobFile], {
    cwd: runtime.working_dir,
    detached: true,
    stdio: "ignore",
    env: { ...process.env },
  });
  worker.unref();
  return { background: true, job_id: delegationId, agent: delegate.agent, status: "queued" };
}

function runDelegate(
  runtime: DelegationRuntime,
  delegate: DelegateRuntime,
  from: string,
  message: string,
  acceptanceCriteria: string | undefined,
  signal: AbortSignal | undefined,
  onProgress: (result: DelegateResult) => void,
): Promise<DelegateResult> {
  const task = [
    `Persistent Pipal delegation message from @agent:${from} in topic ${runtime.topic}.`,
    `Shared working directory: ${runtime.working_dir}`,
    "",
    message,
    acceptanceCriteria ? `\nAcceptance criteria:\n${acceptanceCriteria}` : "",
    "",
    "Perform the work and return concrete results or a precise blocker. This is a continuing thread, so use prior session context when relevant.",
  ].filter(Boolean).join("\n");
  const args = [
    "--mode", "json",
    "--session", delegate.session_file,
    "--append-system-prompt", delegate.prompt_file,
  ];
  if (delegate.provider) args.push("--provider", delegate.provider);
  if (delegate.model) args.push("--model", delegate.model);
  args.push("-p", task);

  return new Promise((resolve, reject) => {
    const proc = spawn(runtime.native_pi, args, {
      cwd: runtime.working_dir,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        PIPAL_AGENT_DIR: delegate.agent_path,
        PIPAL_TOPIC: runtime.topic,
        PIPAL_DISABLE_AUTOGREET: "1",
      },
    });
    let buffer = "";
    let stderr = "";
    let text = "";
    let inputTokens = 0;
    let outputTokens = 0;
    let cost = 0;
    let status = "thinking";
    const tools: ToolRun[] = [];
    const snapshot = (): DelegateResult => ({
      agent: delegate.agent,
      role: delegate.role,
      model: delegate.model,
      text,
      inputTokens,
      outputTokens,
      cost,
      status,
      tools: tools.map((tool) => ({ ...tool })),
    });
    const processEvent = (line: string) => {
      if (!line.trim()) return;
      let event: any;
      try { event = JSON.parse(line); } catch { return; }
      if (event.type === "tool_execution_start") {
        tools.push({ id: String(event.toolCallId), name: String(event.toolName), args: event.args ?? {}, status: "running" });
        status = `using ${event.toolName}`;
        appendEvent(delegate, { type: "tool_call", author: delegate.agent, tool: event.toolName, args: event.args ?? {} });
        onProgress(snapshot());
      } else if (event.type === "tool_execution_update") {
        const tool = tools.find((item) => item.id === String(event.toolCallId));
        if (tool) tool.result = event.partialResult;
        onProgress(snapshot());
      } else if (event.type === "tool_execution_end") {
        const tool = tools.find((item) => item.id === String(event.toolCallId));
        if (tool) {
          tool.result = event.result;
          tool.isError = Boolean(event.isError);
          tool.status = event.isError ? "failed" : "done";
        }
        appendEvent(delegate, {
          type: "tool_result",
          author: delegate.agent,
          tool: event.toolName,
          output: resultText(event.result),
          is_error: Boolean(event.isError),
        });
        onProgress(snapshot());
      } else if (event.type === "message_end" && event.message?.role === "assistant") {
        const current = assistantText(event.message);
        if (current) text = stripPrefix(current, delegate.agent);
        inputTokens += event.message.usage?.input ?? 0;
        outputTokens += event.message.usage?.output ?? 0;
        cost += event.message.usage?.cost?.total ?? 0;
        status = "responding";
        onProgress(snapshot());
      }
    };
    proc.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) processEvent(line);
    });
    proc.stderr.on("data", (chunk) => { stderr += chunk.toString(); });

    let closed = false;
    let aborted = false;
    let timedOut = false;
    const terminate = () => {
      proc.kill("SIGTERM");
      setTimeout(() => { if (!closed) proc.kill("SIGKILL"); }, 3000);
    };
    const timeoutSeconds = Math.max(1, runtime.agent_timeout_seconds ?? 300);
    const timeout = setTimeout(() => { timedOut = true; terminate(); }, timeoutSeconds * 1000);
    proc.on("error", (error) => { closed = true; clearTimeout(timeout); reject(error); });
    proc.on("close", (code) => {
      closed = true;
      clearTimeout(timeout);
      if (buffer.trim()) processEvent(buffer);
      if (timedOut) return reject(new Error(`@agent:${delegate.agent} timed out after ${timeoutSeconds}s`));
      if (aborted) return reject(new Error(`@agent:${delegate.agent} was cancelled`));
      if ((code ?? 1) !== 0) return reject(new Error(stderr.trim() || `@agent:${delegate.agent} exited with code ${code}`));
      status = "done";
      resolve(snapshot());
    });
    const abort = () => { aborted = true; terminate(); };
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
  });
}

export default function delegationExtension(pi: ExtensionAPI) {
  const runtime = loadRuntime();
  if (!runtime || runtime.delegates.length === 0) return;
  const byName = new Map(runtime.delegates.map((delegate) => [delegate.agent.toLowerCase(), delegate]));
  const definitions = new Map(runtime.delegates.map((delegate) => {
    const tools = [
      createBashToolDefinition(runtime.working_dir),
      createReadToolDefinition(runtime.working_dir),
      createWriteToolDefinition(runtime.working_dir),
      createEditToolDefinition(runtime.working_dir),
      createGrepToolDefinition(runtime.working_dir),
      createFindToolDefinition(runtime.working_dir),
      createLsToolDefinition(runtime.working_dir),
    ];
    return [delegate.agent, new Map(tools.map((tool) => [tool.name, tool]))];
  }));
  const renderState = new Map<string, { state: any; call?: any; result?: any }>();
  const queues = new Map<string, Promise<unknown>>();
  let callsThisTurn = 0;
  let directAbort: AbortController | undefined;
  let directLoader: Loader | undefined;
  let backgroundPoller: NodeJS.Timeout | undefined;
  let watchedDelegation: string | undefined;
  let joinedDelegation: string | undefined;
  const watchedOffsets = new Map<string, number>();

  const renderTools = (result: DelegateResult, expanded: boolean, theme: any): Container => {
    const container = new Container();
    const delegateDefinitions = definitions.get(result.agent);
    let first = true;
    for (const tool of result.tools) {
      const key = `${result.agent}:${tool.id}`;
      const slot = renderState.get(key) ?? { state: {} };
      renderState.set(key, slot);
      const definition = delegateDefinitions?.get(tool.name);
      const partial = tool.status === "running";
      const context = {
        args: tool.args,
        toolCallId: tool.id,
        invalidate: () => {},
        state: slot.state,
        cwd: runtime.working_dir,
        executionStarted: true,
        argsComplete: true,
        isPartial: partial,
        expanded,
        showImages: false,
        isError: Boolean(tool.isError),
      };
      const box = new Box(1, 1, (value) => theme.bg(partial ? "toolPendingBg" : tool.isError ? "toolErrorBg" : "toolSuccessBg", value));
      box.addChild(new Text(theme.fg("accent", theme.bold(`@agent:${result.agent}`)), 0, 0));
      if (definition?.renderCall) {
        slot.call = definition.renderCall(tool.args, theme, { ...context, lastComponent: slot.call });
        box.addChild(slot.call);
      } else box.addChild(new Text(`${tool.name} ${JSON.stringify(tool.args)}`, 0, 0));
      if (tool.result) {
        if (definition?.renderResult) {
          slot.result = definition.renderResult(tool.result, { expanded, isPartial: partial }, theme, { ...context, lastComponent: slot.result });
          box.addChild(slot.result);
        } else {
          const output = resultText(tool.result);
          if (output) box.addChild(new Text(output, 0, 0));
        }
      }
      if (!first) container.addChild(new Spacer(1));
      container.addChild(box);
      first = false;
    }
    return container;
  };

  const runQueued = async (
    delegate: DelegateRuntime,
    from: string,
    message: string,
    acceptance: string | undefined,
    signal: AbortSignal | undefined,
    onProgress: (result: DelegateResult) => void,
  ) => {
    const previous = queues.get(delegate.agent) ?? Promise.resolve();
    const operation = previous.catch(() => undefined).then(() =>
      runDelegate(runtime, delegate, from, message, acceptance, signal, onProgress));
    queues.set(delegate.agent, operation);
    return operation;
  };

  const available = runtime.delegates.map((delegate) => `@agent:${delegate.agent}`).join(", ");
  pi.registerTool({
    name: "pipal_delegate",
    label: "Delegate to Pipal agent",
    description: `Hold a persistent delegation thread with another registered Pipal agent. Available: ${available}. Use repeated calls to review, correct, and finish delegated work.`,
    promptSnippet: "Delegate outcome-oriented work to a persistent Pipal agent",
    promptGuidelines: [
      "You own every delegated outcome. Frame the goal, context, and acceptance criteria instead of relaying the user's words.",
      "Inspect the delegate's work. Continue the same agent thread with corrections or follow-up requests until the outcome is complete or genuinely blocked.",
      "Validate claims and artifacts where practical, then report the completed result rather than merely forwarding the delegate's response.",
      "Use parallel pipal_delegate calls when independent work can safely happen concurrently.",
      "Foreground is the default. Use background mode only when the owner explicitly asks, or after suggesting it for long independent work.",
      "Respect user approval boundaries for critical or external actions.",
    ],
    parameters: Type.Object({
      agent: Type.String({ description: "Registered Pipal agent name, without @agent:" }),
      message: Type.String({ description: "The next clear message in this persistent delegation thread" }),
      acceptance_criteria: Type.Optional(Type.String({ description: "Concrete conditions for considering this delegated work complete" })),
      mode: Type.Optional(Type.Union([
        Type.Literal("foreground"),
        Type.Literal("background"),
      ], { description: "Foreground by default; background only when explicitly requested" })),
      delegation_id: Type.Optional(Type.String({ description: "Existing delegation id when continuing or correcting the same managed outcome" })),
    }),
    renderShell: "self",
    async execute(_id, params, signal, onUpdate) {
      const delegate = byName.get(params.agent.replace(/^@?agent:/, "").toLowerCase());
      if (!delegate) throw new Error(`Unknown Pipal agent ${params.agent}. Available: ${available}`);
      if (callsThisTurn >= (runtime.max_turns ?? 8)) throw new Error(`Delegation turn budget reached (${runtime.max_turns ?? 8})`);
      callsThisTurn += 1;
      const delegationId = params.delegation_id ?? `dg-${randomUUID().slice(0, 8)}`;
      if (params.mode === "background") {
        const background = startBackgroundJob(runtime, delegate, params.message, params.acceptance_criteria, { delegationId });
        return {
          content: [{ type: "text", text: `Background delegation ${background.job_id} assigned to @agent:${delegate.agent}. It will continue if this TUI closes.` }],
          details: background,
        };
      }
      appendEvent(delegate, {
        type: "message",
        author: runtime.primary,
        content: params.message,
        acceptance_criteria: params.acceptance_criteria,
        delegation_id: delegationId,
      });
      const result = await runQueued(delegate, runtime.primary, params.message, params.acceptance_criteria, signal, (partial) => {
        onUpdate?.({ content: [{ type: "text", text: partial.text || `@agent:${delegate.agent} is ${partial.status}…` }], details: partial });
      });
      result.delegationId = delegationId;
      appendEvent(delegate, { type: "message", author: delegate.agent, content: result.text || "(no response)", delegation_id: delegationId });
      return {
        content: [{ type: "text", text: `Delegation ${delegationId}\n\n${result.text || "(no response)"}` }],
        details: result,
        usage: {
          input: result.inputTokens,
          output: result.outputTokens,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: result.inputTokens + result.outputTokens,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: result.cost },
        },
      };
    },
    renderCall(args, theme) {
      return new Text(`${theme.fg("accent", theme.bold(`@agent:${String(args.agent).replace(/^@?agent:/, "")}`))}\n${theme.fg("dim", String(args.message ?? ""))}`, 1, 0);
    },
    renderResult(result, { expanded, isPartial }, theme) {
      const details = result.details as DelegateResult | BackgroundResult | undefined;
      if (!details) return new Text("", 0, 0);
      if ("background" in details) {
        return new Text(theme.fg("accent", `↗ ${details.job_id} · @agent:${details.agent} · running in background`), 1, 0);
      }
      const container = renderTools(details, expanded, theme);
      if (details.text || !isPartial) {
        const response = new Box(1, 1, (value) => theme.bg("toolSuccessBg", value));
        response.addChild(new Markdown(`**@agent:${details.agent}:** ${details.text || "(no response)"}`, 0, 0, getMarkdownTheme()));
        if (details.tools.length > 0) container.addChild(new Spacer(1));
        container.addChild(response);
      }
      return container;
    },
  });

  const teams = new Map((runtime.teams ?? []).map((team) => [team.name.toLowerCase(), team]));
  const teamNames = [...teams.values()].map((team) => team.name).join(", ");
  if (teams.size > 0) pi.registerTool({
    name: "pipal_delegate_team",
    label: "Delegate to Pipal team",
    description: `Assign one managed outcome to a saved Pipal team. Teams: ${teamNames}. Members work in parallel; inspect their results, follow up with individuals as needed, and synthesize the outcome.`,
    promptSnippet: "Coordinate outcome-oriented work across a saved Pipal team",
    promptGuidelines: [
      "Use a team when independent specialist perspectives or parallel work add value.",
      "You remain the accountable owner: compare contributions, resolve gaps with follow-up delegations, and deliver one synthesis.",
      "Detailed member activity stays compact unless the owner asks to watch or join it.",
      "Foreground is the default. Use background only when explicitly requested or approved.",
    ],
    parameters: Type.Object({
      team: Type.String({ description: "Saved Pipal team name" }),
      message: Type.String({ description: "Shared goal, context, and requested contribution" }),
      acceptance_criteria: Type.Optional(Type.String({ description: "Conditions the combined team outcome must satisfy" })),
      mode: Type.Optional(Type.Union([Type.Literal("foreground"), Type.Literal("background")])),
      delegation_id: Type.Optional(Type.String({ description: "Existing team delegation id for a follow-up round" })),
    }),
    renderShell: "self",
    async execute(_id, params, signal, onUpdate) {
      const team = teams.get(params.team.toLowerCase());
      if (!team) throw new Error(`Unknown Pipal team ${params.team}. Available: ${teamNames}`);
      const participants = team.members
        .map((member) => ({ member, delegate: byName.get(member.agent.toLowerCase()) }))
        .filter((item): item is { member: { agent: string; role?: string }; delegate: DelegateRuntime } => Boolean(item.delegate));
      if (participants.length === 0) throw new Error(`Team ${team.name} has no available delegates besides the primary agent`);
      const delegationId = params.delegation_id ?? `dg-${randomUUID().slice(0, 8)}`;
      if (params.mode === "background") {
        const jobs = participants.map(({ delegate }) => startBackgroundJob(
          runtime, delegate, params.message, params.acceptance_criteria,
          { delegationId, team: team.name },
        ));
        const details: TeamDelegateResult = { team: team.name, delegation_id: delegationId, background: true, results: [], jobs };
        return {
          content: [{ type: "text", text: `Background team delegation ${delegationId} started with ${participants.map(({ delegate }) => `@agent:${delegate.agent}`).join(", ")}. It will continue if this TUI closes.` }],
          details,
        };
      }
      const partial = new Map<string, DelegateResult>();
      const results = await Promise.all(participants.map(async ({ member, delegate }) => {
        const roleContext = `You are contributing as ${member.role ?? delegate.role} in team ${team.name}.\n\n${params.message}`;
        appendEvent(delegate, {
          type: "message", author: runtime.primary, content: roleContext,
          acceptance_criteria: params.acceptance_criteria, delegation_id: delegationId, team: team.name,
        });
        const result = await runQueued(delegate, runtime.primary, roleContext, params.acceptance_criteria, signal, (update) => {
          update.delegationId = delegationId;
          partial.set(delegate.agent, update);
          onUpdate?.({
            content: [{ type: "text", text: `${partial.size}/${participants.length} team members active` }],
            details: { team: team.name, delegation_id: delegationId, background: false, results: [...partial.values()] } as TeamDelegateResult,
          });
        });
        result.delegationId = delegationId;
        appendEvent(delegate, {
          type: "message", author: delegate.agent, content: result.text || "(no response)",
          delegation_id: delegationId, team: team.name,
        });
        return result;
      }));
      const details: TeamDelegateResult = { team: team.name, delegation_id: delegationId, background: false, results };
      return {
        content: [{ type: "text", text: `Team delegation ${delegationId}\n\n${results.map((result) => `@agent:${result.agent}: ${result.text}`).join("\n\n")}` }],
        details,
      };
    },
    renderCall(args, theme) {
      return new Text(`${theme.fg("accent", theme.bold(`@team:${args.team}`))}\n${theme.fg("dim", String(args.message ?? ""))}`, 1, 0);
    },
    renderResult(result, { expanded }, theme) {
      const details = result.details as TeamDelegateResult | undefined;
      if (!details) return new Text("", 0, 0);
      if (details.background) {
        return new Text(theme.fg("accent", `↗ ${details.delegation_id} · @team:${details.team} · ${details.jobs?.length ?? 0} agents running in background`), 1, 0);
      }
      if (!expanded) {
        const active = details.results.filter((item) => item.status === "running").length;
        const state = active ? `${active} active` : `${details.results.length} contributions complete`;
        return new Text(theme.fg("accent", `${details.delegation_id} · @team:${details.team} · ${state}`), 1, 0);
      }
      const container = new Container();
      details.results.forEach((memberResult, index) => {
        if (index) container.addChild(new Spacer(1));
        const tools = renderTools(memberResult, expanded, theme);
        container.addChild(tools);
        if (memberResult.text) {
          const response = new Box(1, 1, (value) => theme.bg("toolSuccessBg", value));
          response.addChild(new Markdown(`**@agent:${memberResult.agent}:** ${memberResult.text}`, 0, 0, getMarkdownTheme()));
          container.addChild(response);
        }
      });
      return container;
    },
  });

  pi.registerEntryRenderer("pipal-direct-owner", (entry, _options, _theme) => {
    const data = entry.data as { text: string; targets: string };
    return new Markdown(`**Owner → ${data.targets}:**\n\n${data.text}`, 0, 0, getMarkdownTheme());
  });
  pi.registerEntryRenderer("pipal-direct-tools", (entry, { expanded }, theme) =>
    renderTools((entry.data as { result: DelegateResult }).result, expanded, theme));
  pi.registerEntryRenderer("pipal-direct-reply", (entry, _options, _theme) => {
    const data = entry.data as { agent: string; text: string };
    return new Markdown(`**@agent:${data.agent}:** ${data.text}`, 0, 0, getMarkdownTheme());
  });
  pi.registerEntryRenderer("pipal-direct-error", (entry, _options, theme) =>
    new Text(theme.fg("error", `Delegation error: ${(entry.data as { text: string }).text}`), 0, 0));
  pi.registerMessageRenderer("pipal-delegation-complete", (message, _options, theme) =>
    new Text(theme.fg("accent", `Delegation ready for primary review: ${(message.details as any)?.delegation_id ?? ""}`), 0, 0));
  pi.registerEntryRenderer("pipal-delegation-event", (entry, _options, theme) => {
    const { job, event } = entry.data as any;
    const prefix = theme.fg("accent", theme.bold(`@agent:${job.delegate.agent}`));
    if (event.type === "tool_execution_start") {
      return new Text(`${prefix} ${theme.fg("dim", `→ ${event.toolName} ${JSON.stringify(event.args ?? {})}`)}`, 0, 0);
    }
    if (event.type === "tool_execution_end") {
      const output = resultText(event.result);
      return new Text(`${prefix} ${theme.fg(event.isError ? "error" : "success", `← ${event.toolName}`)}${output ? `\n${output}` : ""}`, 0, 0);
    }
    const text = assistantText(event.message);
    return new Markdown(`**@agent:${job.delegate.agent}:** ${text}`, 0, 0, getMarkdownTheme());
  });
  pi.registerEntryRenderer("pipal-background-result", (entry, _options, theme) => {
    const job = entry.data as any;
    const color = job.status === "completed" ? "success" : "error";
    const body = job.status === "completed" ? job.result : job.error;
    return new Markdown(`${theme.fg(color, theme.bold(`${job.id} · @agent:${job.delegate.agent} · ${job.status}`))}\n\n${body ?? ""}`, 0, 0, getMarkdownTheme());
  });

  const readBackgroundJobs = (): any[] => {
    if (!runtime.background_root || !fs.existsSync(runtime.background_root)) return [];
    const jobs: any[] = [];
    for (const name of fs.readdirSync(runtime.background_root)) {
      const jobFile = `${runtime.background_root}/${name}/job.json`;
      try { jobs.push(JSON.parse(fs.readFileSync(jobFile, "utf8"))); } catch { /* incomplete job write */ }
    }
    return jobs.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  };
  const reportWatchedEvents = () => {
    if (!watchedDelegation) return;
    for (const job of readBackgroundJobs().filter((item) => item.id === watchedDelegation || item.delegation_id === watchedDelegation)) {
      const eventFile = `${runtime.background_root}/${job.id}/events.jsonl`;
      if (!fs.existsSync(eventFile)) continue;
      const lines = fs.readFileSync(eventFile, "utf8").split("\n").filter(Boolean);
      const offset = watchedOffsets.get(job.id) ?? 0;
      for (const line of lines.slice(offset)) {
        try {
          const event = JSON.parse(line);
          if (["tool_execution_start", "tool_execution_end"].includes(event.type)
              || (event.type === "message_end" && assistantText(event.message))) {
            pi.appendEntry("pipal-delegation-event", { job, event });
          }
        } catch { /* partial event */ }
      }
      watchedOffsets.set(job.id, lines.length);
    }
  };
  const reportFinishedJobs = () => {
    const jobs = readBackgroundJobs();
    for (const job of jobs) {
      if (job.reported || !["completed", "failed", "cancelled"].includes(job.status)) continue;
      pi.appendEntry("pipal-background-result", job);
      job.reported = true;
      fs.writeFileSync(`${runtime.background_root}/${job.id}/job.json`, `${JSON.stringify(job, null, 2)}\n`, "utf8");
    }
    const groups = new Map<string, any[]>();
    for (const job of jobs) {
      const id = job.delegation_id ?? job.id;
      groups.set(id, [...(groups.get(id) ?? []), job]);
    }
    for (const [id, members] of groups) {
      if (!members.every((job) => ["completed", "failed", "cancelled"].includes(job.status))) continue;
      const notificationDir = `${runtime.background_root}/.notifications`;
      const marker = `${notificationDir}/${id}.json`;
      if (fs.existsSync(marker)) continue;
      fs.mkdirSync(notificationDir, { recursive: true });
      fs.writeFileSync(marker, `${JSON.stringify({ delegation_id: id, notified_at: new Date().toISOString() })}\n`, "utf8");
      pi.sendMessage({
        customType: "pipal-delegation-complete",
        content: `Background delegation ${id} has finished. You remain accountable for the outcome. Use pipal_delegation_status with job_id ${id} now, inspect every result and failure against the acceptance criteria, request any necessary corrections through the persistent agent threads, validate where practical, and report one concise completed outcome or genuine blocker to the owner.`,
        display: true,
        details: { delegation_id: id },
      }, { triggerTurn: true, deliverAs: "followUp" });
    }
  };

  pi.registerTool({
    name: "pipal_delegation_status",
    label: "Check background delegations",
    description: "List persistent background delegation jobs or retrieve one completed result for review.",
    promptSnippet: "Inspect background delegation status and results",
    parameters: Type.Object({
      job_id: Type.Optional(Type.String({ description: "Optional delegation id such as dg-1234abcd" })),
    }),
    async execute(_id, params) {
      const jobs = readBackgroundJobs();
      const selected = params.job_id ? jobs.filter((job) => job.id === params.job_id || job.delegation_id === params.job_id) : jobs;
      if (params.job_id && selected.length === 0) throw new Error(`Unknown background delegation ${params.job_id}`);
      const summary = selected.map((job) => ({
        id: job.id,
        delegation_id: job.delegation_id ?? job.id,
        team: job.team,
        agent: job.delegate.agent,
        status: job.status,
        goal: job.message,
        acceptance_criteria: job.acceptance_criteria,
        result: job.result,
        error: job.error,
        created_at: job.created_at,
        finished_at: job.finished_at,
      }));
      return { content: [{ type: "text", text: JSON.stringify(summary, null, 2) }], details: { count: selected.length } };
    },
  });

  pi.registerCommand("delegations", {
    description: "Show background delegation jobs",
    handler: async (_args, ctx) => {
      const jobs = readBackgroundJobs();
      if (jobs.length === 0) return ctx.ui.notify("No background delegations", "info");
      const grouped = new Map<string, any[]>();
      for (const job of jobs) {
        const id = job.delegation_id ?? job.id;
        grouped.set(id, [...(grouped.get(id) ?? []), job]);
      }
      ctx.ui.notify([...grouped].map(([id, items]) => {
        const team = items[0].team ? ` @team:${items[0].team}` : "";
        const statuses = [...new Set(items.map((item) => item.status))].join("/");
        return `${id}${team} · ${items.length} agent${items.length === 1 ? "" : "s"} · ${statuses}`;
      }).join("\n"), "info");
    },
  });

  pi.registerCommand("cancel-delegation", {
    description: "Cancel background delegated work: /cancel-delegation <dg-id>",
    handler: async (args, ctx) => {
      const id = args.trim();
      if (!id) return ctx.ui.notify("Usage: /cancel-delegation <dg-id>", "warning");
      const jobs = readBackgroundJobs().filter((job) => job.id === id || job.delegation_id === id);
      if (jobs.length === 0) return ctx.ui.notify(`Unknown delegation ${id}`, "error");
      for (const job of jobs) {
        if (job.pid && ["queued", "running"].includes(job.status)) {
          try { process.kill(job.pid, "SIGTERM"); } catch { /* already exited */ }
        }
        if (["queued", "running"].includes(job.status)) {
          job.status = "cancelled";
          job.error = "Cancelled by owner";
          job.finished_at = new Date().toISOString();
          fs.writeFileSync(`${runtime.background_root}/${job.id}/job.json`, `${JSON.stringify(job, null, 2)}\n`, "utf8");
        }
      }
      ctx.ui.notify(`Cancelled ${id}`, "warning");
    },
  });

  pi.registerCommand("watch", {
    description: "Watch a background delegation: /watch <dg-id>",
    handler: async (args, ctx) => {
      const id = args.trim();
      if (!id) return ctx.ui.notify("Usage: /watch <dg-id>", "warning");
      const found = readBackgroundJobs().some((job) => job.id === id || job.delegation_id === id);
      if (!found) return ctx.ui.notify(`Unknown delegation ${id}`, "error");
      watchedDelegation = id;
      watchedOffsets.clear();
      reportWatchedEvents();
      ctx.ui.notify(`Watching ${id}. Use /detach to stop watching; work continues.`, "info");
    },
  });
  pi.registerCommand("join", {
    description: "Watch and participate in delegated work: /join <dg-id>",
    handler: async (args, ctx) => {
      const id = args.trim();
      if (!id) return ctx.ui.notify("Usage: /join <dg-id>", "warning");
      const found = readBackgroundJobs().some((job) => job.id === id || job.delegation_id === id);
      if (!found) return ctx.ui.notify(`Unknown delegation ${id}`, "error");
      watchedDelegation = id;
      joinedDelegation = id;
      watchedOffsets.clear();
      reportWatchedEvents();
      ctx.ui.notify(`Joined ${id}. Use @agent:<name> or @team; active turns receive interventions as follow-ups.`, "info");
    },
  });
  pi.registerCommand("detach", {
    description: "Stop watching delegated work without cancelling it",
    handler: async (_args, ctx) => {
      if (!watchedDelegation) return ctx.ui.notify("No delegation is currently being watched", "info");
      const id = watchedDelegation;
      watchedDelegation = undefined;
      joinedDelegation = undefined;
      watchedOffsets.clear();
      ctx.ui.notify(`Detached from ${id}; work continues.`, "info");
    },
  });

  pi.on("input", async (event, ctx) => {
    callsThisTurn = 0;
    let text = event.text.replace(/\\@agent:/g, "@agent:").replace(/\\@team/g, "@team");
    const names = [...text.matchAll(/@agent:([\w.-]+)/g)].map((match) => match[1].toLowerCase());
    const teamMentions = [...text.matchAll(/@team(?::([\w.-]+))?/g)];
    for (const match of teamMentions) {
      const teamName = match[1]?.toLowerCase();
      if (teamName) {
        for (const member of teams.get(teamName)?.members ?? []) names.push(member.agent.toLowerCase());
      } else if (joinedDelegation) {
        for (const job of readBackgroundJobs().filter((item) => item.id === joinedDelegation || item.delegation_id === joinedDelegation)) {
          names.push(String(job.delegate.agent).toLowerCase());
        }
      }
    }
    const targets = [...new Set(names)].map((name) => byName.get(name)).filter(Boolean) as DelegateRuntime[];
    if (targets.length === 0) return { action: "continue" };
    if (joinedDelegation) {
      text = `Owner intervention for active delegation ${joinedDelegation}. Treat this as a follow-up in that outcome and consult its persistent transcript as needed.\n\n${text}`;
    }

    pi.appendEntry("pipal-direct-owner", { text, targets: targets.map((target) => `@agent:${target.agent}`).join(", ") });
    directAbort?.abort();
    const controller = new AbortController();
    directAbort = controller;
    ctx.ui.setWidget("pipal-direct-spinner", (tui, theme) => {
      directLoader = new CompactLoader(tui, (value) => theme.fg("accent", value), (value) => theme.fg("muted", value), `Working · ${targets.map((target) => `@agent:${target.agent}`).join(", ")}`);
      return directLoader;
    });
    try {
      if (joinedDelegation) {
        const targetNames = new Set(targets.map((target) => target.agent.toLowerCase()));
        const deadline = Date.now() + (runtime.agent_timeout_seconds ?? 300) * 1000;
        let notified = false;
        while (Date.now() < deadline && !controller.signal.aborted) {
          const active = readBackgroundJobs().some((job) =>
            (job.id === joinedDelegation || job.delegation_id === joinedDelegation)
            && targetNames.has(String(job.delegate.agent).toLowerCase())
            && ["queued", "running"].includes(job.status));
          if (!active) break;
          if (!notified) {
            ctx.ui.notify(`Intervention queued for ${joinedDelegation}; waiting for active agent turns to finish`, "info");
            notified = true;
          }
          await new Promise((resolve) => setTimeout(resolve, 250));
        }
        if (controller.signal.aborted) throw new Error("Joined delegation intervention cancelled");
      }
      await Promise.all(targets.map(async (delegate) => {
        appendEvent(delegate, { type: "message", author: "owner", content: text, delegation_id: joinedDelegation });
        let latest: DelegateResult | undefined;
        const result = await runQueued(delegate, "owner", text, undefined, controller.signal, (partial) => {
          latest = partial;
          if (partial.tools.length > 0) {
            directLoader?.stop();
            directLoader = undefined;
            ctx.ui.setWidget("pipal-direct-spinner", undefined);
            ctx.ui.setWidget(`pipal-direct-live-${delegate.agent}`, (_tui: any, theme: any) => renderTools(latest!, true, theme));
          }
        });
        ctx.ui.setWidget(`pipal-direct-live-${delegate.agent}`, undefined);
        if (result.tools.length > 0) pi.appendEntry("pipal-direct-tools", { result });
        appendEvent(delegate, { type: "message", author: delegate.agent, content: result.text || "(no response)", delegation_id: joinedDelegation });
        pi.appendEntry("pipal-direct-reply", { agent: delegate.agent, text: result.text || "(no response)" });
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pi.appendEntry("pipal-direct-error", { text: message });
      ctx.ui.notify(message, controller.signal.aborted ? "warning" : "error");
    } finally {
      if (directAbort === controller) directAbort = undefined;
      directLoader?.stop();
      directLoader = undefined;
      ctx.ui.setWidget("pipal-direct-spinner", undefined);
      for (const target of targets) ctx.ui.setWidget(`pipal-direct-live-${target.agent}`, undefined);
    }
    return { action: "handled" };
  });

  pi.on("session_start", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    reportFinishedJobs();
    backgroundPoller = setInterval(() => {
      reportWatchedEvents();
      reportFinishedJobs();
    }, 1000);
    const names = new Set(runtime.delegates.map((delegate) => delegate.agent.toLowerCase()));
    ctx.ui.setEditorComponent((tui, theme, keybindings) => new DelegationEditor(
      tui,
      theme,
      keybindings,
      names,
      new Set((runtime.teams ?? []).map((team) => team.name.toLowerCase())),
      () => {
        if (!directAbort) return false;
        directAbort.abort();
        ctx.ui.notify("Cancelling direct agent work", "warning");
        return true;
      },
    ));
    ctx.ui.addAutocompleteProvider((current) => ({
      triggerCharacters: ["@"],
      async getSuggestions(lines, line, col, options) {
        const before = (lines[line] ?? "").slice(0, col);
        const agentMatch = before.match(/(?:^|\s)@agent:([\w.-]*)$/);
        const teamMatch = before.match(/(?:^|\s)@team:([\w.-]*)$/);
        if (!agentMatch && !teamMatch) return current.getSuggestions(lines, line, col, options);
        const query = (agentMatch?.[1] ?? teamMatch?.[1] ?? "").toLowerCase();
        const items = agentMatch
          ? runtime.delegates
              .filter((delegate) => delegate.agent.toLowerCase().includes(query))
              .map((delegate) => ({ value: `@agent:${delegate.agent}`, label: `@agent:${delegate.agent}`, description: delegate.model ?? "Pipal agent" }))
          : (runtime.teams ?? [])
              .filter((team) => team.name.toLowerCase().includes(query))
              .map((team) => ({ value: `@team:${team.name}`, label: `@team:${team.name}`, description: `${team.members.length} members` }));
        if (options.signal.aborted || items.length === 0) return null;
        return { prefix: agentMatch ? `@agent:${agentMatch[1]}` : `@team:${teamMatch![1]}`, items };
      },
      applyCompletion(lines, line, col, item, prefix) {
        return current.applyCompletion(lines, line, col, item, prefix);
      },
      shouldTriggerFileCompletion(lines, line, col) {
        return current.shouldTriggerFileCompletion?.(lines, line, col) ?? true;
      },
    }));
  });

  pi.on("session_shutdown", () => {
    directAbort?.abort();
    directLoader?.stop();
    if (backgroundPoller) clearInterval(backgroundPoller);
    backgroundPoller = undefined;
  });
}
