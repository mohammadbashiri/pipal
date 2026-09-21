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
import { Box, Container, Loader, Markdown, Spacer, Text, truncateToWidth } from "@earendil-works/pi-tui";

class CompactLoader extends Loader {
  override render(width: number): string[] {
    const lines = super.render(width);
    return lines[0] === "" ? lines.slice(1) : lines;
  }
}

interface RuntimeMember {
  agent: string;
  role: string;
  agent_path: string;
  provider?: string;
  model?: string;
  prompt_file: string;
  session_file: string;
}

interface TeamRuntime {
  kind?: "team" | "channel";
  channel?: string;
  team: string;
  owner: string;
  manager?: string;
  topic: string;
  topic_dir: string;
  transcript_file: string;
  working_dir: string;
  native_pi: string;
  max_rounds: number;
  agent_timeout_seconds?: number;
  members: RuntimeMember[];
}

class TeamEditor extends CustomEditor {
  constructor(
    tui: any,
    theme: any,
    private teamKeybindings: any,
    private mentionNames: Set<string>,
    private cancelActive: () => boolean,
  ) {
    super(tui, theme, teamKeybindings);
  }

  override handleInput(data: string): void {
    if (
      this.teamKeybindings.matches(data, "app.interrupt")
      && !this.isShowingAutocomplete()
      && this.cancelActive()
    ) {
      return;
    }
    if (this.teamKeybindings.matches(data, "tui.input.submit") && !this.isShowingAutocomplete()) {
      const text = this.getExpandedText();
      const escaped = text.replace(/@([\w.-]+)/g, (value, name) =>
        this.mentionNames.has(String(name).toLowerCase()) ? `\\${value}` : value);
      if (escaped !== text) {
        // Pi reserves @... for file expansion. Escape known room mentions only
        // at submission time; owner and transcript rendering remain clean.
        this.setText(escaped);
      }
    }
    super.handleInput(data);
  }
}

interface MemberToolRun {
  id: string;
  name: string;
  args: any;
  result?: any;
  isError?: boolean;
  status: "running" | "done" | "failed";
}

interface MemberResult {
  agent: string;
  role: string;
  model?: string;
  text: string;
  turns: number;
  inputTokens: number;
  outputTokens: number;
  cost: number;
  exitCode: number;
  status?: string;
  tools: MemberToolRun[];
}

function loadRuntime(): TeamRuntime | null {
  const runtimePath = process.env.PIPAL_TEAM_RUNTIME;
  if (!runtimePath) return null;
  try {
    return JSON.parse(fs.readFileSync(runtimePath, "utf8")) as TeamRuntime;
  } catch {
    return null;
  }
}

function appendTranscript(runtime: TeamRuntime, event: Record<string, unknown>): void {
  fs.appendFileSync(runtime.transcript_file, `${JSON.stringify({
    schema_version: 1,
    id: randomUUID(),
    timestamp: new Date().toISOString(),
    ...event,
  })}\n`, "utf8");
}

function toolResultText(result: any): string {
  if (!Array.isArray(result?.content)) return "";
  return result.content
    .filter((part: any) => part?.type === "text" && typeof part.text === "string")
    .map((part: any) => part.text)
    .join("\n");
}

function textFromMessage(message: any): string {
  if (!message || message.role !== "assistant" || !Array.isArray(message.content)) return "";
  return message.content
    .filter((part: any) => part?.type === "text" && typeof part.text === "string")
    .map((part: any) => part.text)
    .join("\n")
    .trim();
}

function stripAgentPrefix(text: string, agent: string): string {
  const escaped = agent.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text.replace(new RegExp(`^@?${escaped}(?:\\s*\\([^)]*\\))?\\s*:\\s*`, "i"), "");
}

function readsTranscript(runtime: TeamRuntime, toolName: string, args: any): boolean {
  if (toolName !== "read") return false;
  const requested = String(args?.path ?? args?.file_path ?? "");
  try {
    return fs.realpathSync(requested) === fs.realpathSync(runtime.transcript_file);
  } catch {
    return requested === runtime.transcript_file;
  }
}

function runMember(
  runtime: TeamRuntime,
  member: RuntimeMember,
  from: string,
  message: string,
  signal: AbortSignal | undefined,
  onProgress: (result: MemberResult) => void,
): Promise<MemberResult> {
  const task = [
    `Team message from @${from} in #${runtime.topic}:`,
    `Shared working directory for this launch: ${runtime.working_dir}`,
    "Treat that as the current directory for relative paths and current-directory questions; verify with a tool when needed.",
    "",
    message,
    "",
    `Respond as @${member.agent}, the ${member.role}. Give your independent contribution to the shared discussion. Return only the response body; the UI adds your name and role.`,
  ].join("\n");

  const args = [
    "--mode", "json",
    "--session", member.session_file,
    "--append-system-prompt", member.prompt_file,
  ];
  if (member.provider) args.push("--provider", member.provider);
  if (member.model) args.push("--model", member.model);
  args.push("-p", task);

  return new Promise((resolve, reject) => {
    const proc = spawn(runtime.native_pi, args, {
      cwd: runtime.working_dir,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        PIPAL_AGENT_DIR: member.agent_path,
        PIPAL_TEAM: runtime.team,
        PIPAL_TOPIC: runtime.topic,
        PIPAL_DISABLE_AUTOGREET: "1",
      },
    });

    let buffer = "";
    let stderr = "";
    let finalText = "";
    let turns = 0;
    let inputTokens = 0;
    let outputTokens = 0;
    let cost = 0;
    let status = "thinking";
    let modelError = "";
    const tools: MemberToolRun[] = [];

    const snapshot = (exitCode = -1): MemberResult => ({
      agent: member.agent,
      role: member.role,
      model: member.model,
      text: finalText,
      turns,
      inputTokens,
      outputTokens,
      cost,
      exitCode,
      status,
      tools: tools.map((tool) => ({ ...tool })),
    });

    const processEvent = (line: string) => {
      if (!line.trim()) return;
      let event: any;
      try {
        event = JSON.parse(line);
      } catch {
        return;
      }

      if (event.type === "tool_execution_start") {
        const toolName = String(event.toolName ?? "tool");
        const args = event.args ?? {};
        tools.push({
          id: String(event.toolCallId),
          name: toolName,
          args,
          status: "running",
        });
        appendTranscript(runtime, readsTranscript(runtime, toolName, args) ? {
          type: "history_read",
          author: { kind: "agent", name: member.agent, role: member.role },
        } : {
          type: "tool_call",
          author: { kind: "agent", name: member.agent, role: member.role },
          tool: toolName,
          args,
        });
        status = `using ${toolName}`;
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
          if (!readsTranscript(runtime, tool.name, tool.args)) {
            appendTranscript(runtime, {
              type: "tool_result",
              author: { kind: "agent", name: member.agent, role: member.role },
              tool: tool.name,
              output: toolResultText(event.result),
              is_error: Boolean(event.isError),
            });
          }
        }
        onProgress(snapshot());
      } else if (event.type === "message_end" && event.message?.role === "assistant") {
        const current = textFromMessage(event.message);
        if (current) finalText = stripAgentPrefix(current, member.agent);
        turns += 1;
        const usage = event.message.usage;
        inputTokens += usage?.input ?? 0;
        outputTokens += usage?.output ?? 0;
        cost += usage?.cost?.total ?? 0;
        // Pi can exit successfully even when the model request itself failed.
        // Treat that as a failed member run rather than publishing "(no response)".
        if (event.message.stopReason === "error" || event.message.errorMessage) {
          modelError = String(event.message.errorMessage || "The model returned an error without details.");
          status = "failed";
        } else {
          status = "responding";
        }
        onProgress(snapshot());
      }
    };

    proc.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) processEvent(line);
    });
    let closed = false;
    let aborted = false;
    let timedOut = false;
    const terminate = () => {
      proc.kill("SIGTERM");
      setTimeout(() => { if (!closed) proc.kill("SIGKILL"); }, 3000);
    };
    const timeoutSeconds = Math.max(1, runtime.agent_timeout_seconds ?? 300);
    const timeout = setTimeout(() => {
      timedOut = true;
      status = "timed out";
      terminate();
    }, timeoutSeconds * 1000);

    proc.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    proc.on("error", (error) => {
      closed = true;
      clearTimeout(timeout);
      reject(error);
    });
    proc.on("close", (code) => {
      closed = true;
      clearTimeout(timeout);
      if (buffer.trim()) processEvent(buffer);
      const exitCode = code ?? 1;
      if (timedOut) {
        reject(new Error(`@${member.agent} timed out after ${timeoutSeconds}s`));
        return;
      }
      if (modelError) {
        reject(new Error(`@${member.agent} failed: ${modelError}`));
        return;
      }
      if (aborted) {
        reject(new Error(`@${member.agent} was cancelled`));
        return;
      }
      status = exitCode === 0 ? "done" : "failed";
      if (exitCode !== 0) {
        reject(new Error(stderr.trim() || `@${member.agent} exited with code ${exitCode}`));
        return;
      }
      resolve(snapshot(exitCode));
    });

    const abort = () => {
      aborted = true;
      status = "aborted";
      terminate();
    };
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
  });
}

export default function teamChatExtension(pi: ExtensionAPI) {
  const runtime = loadRuntime();
  if (!runtime) return;

  const lockFile = process.env.PIPAL_TEAM_LOCK_FILE;
  if (lockFile) {
    process.once("exit", () => {
      try {
        const owner = Number(fs.readFileSync(lockFile, "utf8").trim());
        if (owner === process.pid) fs.unlinkSync(lockFile);
      } catch {
        // A stale or replaced lock must not make shutdown fail.
      }
    });
  }

  const manager = runtime.members.find((item) => item.agent === runtime.manager);
  const byName = new Map(runtime.members.map((item) => [item.agent.toLowerCase(), item]));
  const toolDefinitions = new Map(runtime.members.map((member) => {
    const definitions = [
      createBashToolDefinition(runtime.working_dir),
      createReadToolDefinition(runtime.working_dir),
      createWriteToolDefinition(runtime.working_dir),
      createEditToolDefinition(runtime.working_dir),
      createGrepToolDefinition(runtime.working_dir),
      createFindToolDefinition(runtime.working_dir),
      createLsToolDefinition(runtime.working_dir),
    ];
    return [member.agent, new Map(definitions.map((definition) => [definition.name, definition]))];
  }));
  const nestedRenderers = new Map<string, { state: any; call?: any; result?: any }>();
  const active = new Set<string>();
  const agentsWithVisibleTools = new Set<string>();
  const queues = new Map<string, Promise<unknown>>();
  let activityLoader: Loader | undefined;
  let delegationsThisRun = 0;
  let currentRoomAbort: AbortController | undefined;
  const delegationLimit = Math.max(1, runtime.max_rounds) * Math.max(1, runtime.members.length);

  const setActivity = (ctx: any) => {
    const spinningAgents = [...active].filter((name) => !agentsWithVisibleTools.has(name));
    if (spinningAgents.length === 0) {
      activityLoader?.stop();
      activityLoader = undefined;
      ctx.ui.setWidget("pipal-team-spinner", undefined);
      ctx.ui.setStatus("pipal-team-activity", undefined);
      return;
    }
    const agents = spinningAgents.map((name) => `@${name}`).join(", ");
    const message = `Working · ${agents}`;
    if (activityLoader) {
      activityLoader.setMessage(message);
      return;
    }
    ctx.ui.setWidget("pipal-team-spinner", (tui: any, theme: any) => {
      activityLoader = new CompactLoader(
        tui,
        (text) => theme.fg("accent", text),
        (text) => theme.fg("muted", text),
        message,
      );
      return activityLoader;
    });
    ctx.ui.setStatus("pipal-team-activity", `team: ${agents}`);
  };

  const renderAgentTools = (memberResults: MemberResult[], expanded: boolean, theme: any) => {
    const container = new Container();
    let firstTool = true;
    for (const memberResult of memberResults) {
      const member = byName.get(memberResult.agent.toLowerCase());
      for (const tool of memberResult.tools ?? []) {
        const key = `${memberResult.agent}:${tool.id}`;
        const slot = nestedRenderers.get(key) ?? { state: {} };
        nestedRenderers.set(key, slot);
        const definition = member ? toolDefinitions.get(member.agent)?.get(tool.name) : undefined;
        const partial = tool.status === "running";
        const contextBase = {
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
        const box = new Box(1, 1, (text) => theme.bg(
          partial ? "toolPendingBg" : tool.isError ? "toolErrorBg" : "toolSuccessBg",
          text,
        ));
        box.addChild(new Text(
          theme.fg("accent", theme.bold(`@${memberResult.agent} (${memberResult.role})`)),
          0,
          0,
        ));
        if (definition?.renderCall) {
          slot.call = definition.renderCall(tool.args, theme, { ...contextBase, lastComponent: slot.call });
          box.addChild(slot.call);
        } else {
          box.addChild(new Text(`${tool.name} ${JSON.stringify(tool.args)}`, 0, 0));
        }
        if (tool.result) {
          if (definition?.renderResult) {
            slot.result = definition.renderResult(
              tool.result,
              { expanded, isPartial: partial },
              theme,
              { ...contextBase, lastComponent: slot.result },
            );
            box.addChild(slot.result);
          } else {
            const text = toolResultText(tool.result);
            if (text) box.addChild(new Text(text, 0, 0));
          }
        }
        if (!firstTool) container.addChild(new Spacer(1));
        container.addChild(box);
        firstTool = false;
      }
    }
    return container;
  };

  pi.registerEntryRenderer("pipal-team-owner", (entry, _options, _theme) => {
    const data = entry.data as { owner: string; text: string };
    return new Markdown(`**${data.owner} (Owner)**\n\n${data.text}`, 0, 0, getMarkdownTheme());
  });

  pi.registerEntryRenderer("pipal-team-system", (entry, _options, theme) => {
    const data = entry.data as { level: "error" | "warning"; text: string };
    const color = data.level === "error" ? "error" : "warning";
    return new Text(theme.fg(color, `Team ${data.level}: ${data.text}`), 0, 0);
  });

  pi.registerEntryRenderer("pipal-team-agent-tools", (entry, { expanded }, theme) => {
    const data = entry.data as { result: MemberResult };
    return renderAgentTools([data.result], expanded, theme);
  });

  pi.registerEntryRenderer("pipal-team-agent-reply", (entry, _options, _theme) => {
    const data = entry.data as { agent: string; role: string; text: string };
    return new Markdown(`**@${data.agent} (${data.role}):** ${data.text}`, 0, 0, getMarkdownTheme());
  });

  const mentionedMembers = (text: string, sender: string, ancestors: Set<string>): RuntimeMember[] => {
    const found: RuntimeMember[] = [];
    const seen = new Set<string>();
    for (const match of text.matchAll(/@([\w.-]+)/g)) {
      const name = match[1].toLowerCase();
      const candidates = name === "team" || (runtime.kind === "channel" && (name === "channel" || name === "all"))
        ? runtime.members
        : ([byName.get(name)].filter(Boolean) as RuntimeMember[]);
      for (const member of candidates) {
        if (member.agent === sender || ancestors.has(member.agent) || seen.has(member.agent)) continue;
        seen.add(member.agent);
        found.push(member);
      }
    }
    return found;
  };

  const runRoomThread = async (
    member: RuntimeMember,
    from: string,
    message: string,
    signal: AbortSignal,
    ctx: any,
    ancestors = new Set<string>(),
  ): Promise<MemberResult> => {
    if (delegationsThisRun >= delegationLimit) {
      throw new Error(`Team turn budget reached (${delegationLimit} agent turns).`);
    }
    delegationsThisRun += 1;
    const previous = queues.get(member.agent) ?? Promise.resolve();
    const operation = previous.catch(() => undefined).then(async () => {
      active.add(member.agent);
      setActivity(ctx);
      let latest: MemberResult | undefined;
      try {
        const result = await runMember(runtime, member, from, message, signal, (partial) => {
          latest = partial;
          if (partial.tools.length > 0) agentsWithVisibleTools.add(member.agent);
          setActivity(ctx);
          ctx.ui.setWidget("pipal-team-live-tools", (_tui: any, theme: any) =>
            renderAgentTools(latest ? [latest] : [], true, theme));
        });
        if (result.tools.length > 0) {
          pi.appendEntry("pipal-team-agent-tools", { result });
        }
        appendTranscript(runtime, {
          type: "message",
          author: { kind: "agent", name: result.agent, role: result.role },
          content: result.text || "(no response)",
        });
        pi.appendEntry("pipal-team-agent-reply", {
          agent: result.agent,
          role: result.role,
          text: result.text || "(no response)",
        });
        return result;
      } finally {
        ctx.ui.setWidget("pipal-team-live-tools", undefined);
        agentsWithVisibleTools.delete(member.agent);
        active.delete(member.agent);
        setActivity(ctx);
      }
    });
    queues.set(member.agent, operation);
    const result = await operation;
    const nextAncestors = new Set(ancestors).add(member.agent);
    const mentioned = mentionedMembers(result.text, member.agent, nextAncestors);
    if (mentioned.length === 0) return result;

    const replies = await Promise.all(mentioned.map((target) => runRoomThread(
      target,
      member.agent,
      `@${member.agent} said:\n\n${result.text}\n\nYou were explicitly mentioned. Respond to @${member.agent}'s message.`,
      signal,
      ctx,
      nextAncestors,
    )));
    const gathered = replies.map((reply) => `@${reply.agent} (${reply.role}): ${reply.text}`).join("\n\n");
    return runRoomThread(
      member,
      "team",
      `The agents you addressed replied:\n\n${gathered}\n\nContinue your response to the owner using their input. Only @mention someone if you need another response from them.`,
      signal,
      ctx,
      ancestors,
    );
  };

  pi.on("input", async (event, ctx) => {
    delegationsThisRun = 0;
    const text = event.text.replace(/\\@/g, "@");
    const mentioned: RuntimeMember[] = [];
    const seen = new Set<string>();
    let wholeTeam = false;
    for (const match of text.matchAll(/@([\w.-]+)/g)) {
      const name = match[1].toLowerCase();
      if (name === "team" || (runtime.kind === "channel" && (name === "channel" || name === "all"))) {
        wholeTeam = true;
        continue;
      }
      const member = byName.get(name);
      if (member && !seen.has(member.agent)) {
        seen.add(member.agent);
        mentioned.push(member);
      }
    }
    const targets = wholeTeam
      ? runtime.members
      : mentioned.length > 0
        ? mentioned
        : runtime.kind === "channel" ? [] : manager ? [manager] : [];

    appendTranscript(runtime, {
      type: "message",
      author: { kind: "owner", name: runtime.owner, role: "Owner" },
      targets: targets.map((member) => member.agent),
      content: text,
    });
    pi.appendEntry("pipal-team-owner", { owner: runtime.owner, text });
    // In a channel an unmentioned message is for the human conversation, not
    // an implicit request for an agent turn. Mention @agent or @team to act.
    if (targets.length === 0) {
      if (runtime.kind !== "channel") ctx.ui.notify("This team has no available agents", "error");
      return { action: "handled" };
    }

    currentRoomAbort?.abort();
    const roomAbort = new AbortController();
    currentRoomAbort = roomAbort;
    try {
      const directTargets = new Set(targets.map((target) => target.agent));
      await Promise.all(targets.map((target) => runRoomThread(
        target,
        runtime.owner,
        text,
        roomAbort.signal,
        ctx,
        new Set([...directTargets].filter((agent) => agent !== target.agent)),
      )));
    } catch (error) {
      roomAbort.abort();
      const message = error instanceof Error ? error.message : String(error);
      const cancelled = roomAbort.signal.aborted && /cancelled|aborted/i.test(message);
      const level = cancelled ? "warning" : "error";
      appendTranscript(runtime, {
        type: level,
        content: cancelled ? "Active team work was cancelled." : message,
      });
      pi.appendEntry("pipal-team-system", {
        level,
        text: cancelled ? "Active team work was cancelled." : message,
      });
      ctx.ui.notify(message, level);
    } finally {
      if (currentRoomAbort === roomAbort) {
        currentRoomAbort = undefined;
        ctx.ui.setWidget("pipal-team-live-tools", undefined);
        ctx.ui.setStatus("pipal-team-activity", undefined);
      }
    }
    return { action: "handled" };
  });

  pi.registerCommand("team-stop", {
    description: "Cancel active team work",
    handler: async (_args, ctx) => {
      if (!currentRoomAbort) {
        ctx.ui.notify("No team work is active", "info");
        return;
      }
      currentRoomAbort.abort();
      ctx.ui.setStatus("pipal-team-activity", "team: cancelling…");
      ctx.ui.notify("Cancelling active team work", "warning");
    },
  });

  pi.on("session_shutdown", () => {
    activityLoader?.stop();
    activityLoader = undefined;
    currentRoomAbort?.abort();
  });

  pi.on("session_start", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    try {
      for (const line of fs.readFileSync(runtime.transcript_file, "utf8").split("\n")) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "message" && event.author?.kind === "owner") {
          pi.appendEntry("pipal-team-owner", { owner: event.author.name, text: event.content });
        } else if (event.type === "message" && event.author?.kind === "agent") {
          pi.appendEntry("pipal-team-agent-reply", {
            agent: event.author.name,
            role: event.author.role ?? "Member",
            text: event.content,
          });
        } else if (event.type === "error" || event.type === "warning") {
          pi.appendEntry("pipal-team-system", { level: event.type, text: event.content });
        }
      }
    } catch {
      ctx.ui.notify("Could not restore the shared team transcript", "warning");
    }
    appendTranscript(runtime, {
      type: "context",
      working_dir: runtime.working_dir,
    });
    ctx.ui.setTitle(`pipal · ${runtime.team} · ${runtime.topic}`);
    const mentionNames = new Set(["team", ...(runtime.kind === "channel" ? ["channel", "all"] : []), ...runtime.members.map((item) => item.agent.toLowerCase())]);
    ctx.ui.setEditorComponent((tui, theme, keybindings) =>
      new TeamEditor(tui, theme, keybindings, mentionNames, () => {
        if (!currentRoomAbort) return false;
        currentRoomAbort.abort();
        ctx.ui.setStatus("pipal-team-activity", "team: cancelling…");
        ctx.ui.notify("Cancelling active team work", "warning");
        return true;
      })
    );
    ctx.ui.setHeader((_tui, theme) => ({
      render(width: number) {
        const lines = [
          theme.fg("accent", theme.bold(`${runtime.kind === "channel" ? "PIPAL CHANNEL" : "PIPAL TEAM"}  ${runtime.channel ?? runtime.team}`)),
          theme.fg("muted", `topic: ${runtime.topic}`),
          theme.fg("muted", `working directory: ${runtime.working_dir}`),
          theme.fg("muted", `owner: ${runtime.owner}`),
          ...(runtime.manager ? [theme.fg("muted", `manager: @${runtime.manager}`)] : []),
          ...runtime.members
            .filter((item) => item.agent !== runtime.manager)
            .map((item) => theme.fg("muted", `${item.role}: @${item.agent}`)),
        ];
        return ["", ...lines.map((line) => truncateToWidth(line, width)), ""];
      },
      invalidate() {},
    }));
    ctx.ui.addAutocompleteProvider((current) => ({
      triggerCharacters: ["@"],
      async getSuggestions(lines, line, col, options) {
        const before = (lines[line] ?? "").slice(0, col);
        const match = before.match(/(?:^|\s)@([\w.-]*)$/);
        if (!match) return current.getSuggestions(lines, line, col, options);
        const query = (match[1] ?? "").toLowerCase();
        const candidates = [
          ...(runtime.kind === "channel"
            ? [
                { value: "@channel", label: "@channel", description: "Address every channel member" },
                { value: "@all", label: "@all", description: "Address every channel member" },
                { value: "@team", label: "@team", description: "Legacy alias for everyone" },
              ]
            : [{ value: "@team", label: "@team", description: "Address the whole team" }]),
          ...runtime.members.map((item) => ({
            value: `@${item.agent}`,
            label: `@${item.agent}`,
            description: `${item.role}${item.model ? ` · ${item.model}` : ""}`,
          })),
        ].filter((item) => item.value.toLowerCase().includes(query));
        if (options.signal.aborted || candidates.length === 0) return null;
        return { prefix: `@${match[1] ?? ""}`, items: candidates };
      },
      applyCompletion(lines, line, col, item, prefix) {
        return current.applyCompletion(lines, line, col, item, prefix);
      },
      shouldTriggerFileCompletion(lines, line, col) {
        return current.shouldTriggerFileCompletion?.(lines, line, col) ?? true;
      },
    }));
  });


}
