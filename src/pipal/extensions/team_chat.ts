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
import { Box, Container, Markdown, Spacer, Text, truncateToWidth } from "@earendil-works/pi-tui";
import { Type } from "typebox";

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
  team: string;
  owner: string;
  manager: string;
  topic: string;
  topic_dir: string;
  transcript_file: string;
  working_dir: string;
  native_pi: string;
  max_rounds: number;
  members: RuntimeMember[];
}

class TeamEditor extends CustomEditor {
  constructor(tui: any, theme: any, private teamKeybindings: any, private mentionNames: Set<string>) {
    super(tui, theme, teamKeybindings);
  }

  override handleInput(data: string): void {
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

interface DelegationResult {
  results: MemberResult[];
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
    proc.on("error", reject);
    proc.on("close", (code) => {
      if (buffer.trim()) processEvent(buffer);
      const exitCode = code ?? 1;
      status = exitCode === 0 ? "done" : "failed";
      if (exitCode !== 0) {
        reject(new Error(stderr.trim() || `@${member.agent} exited with code ${exitCode}`));
        return;
      }
      resolve(snapshot(exitCode));
    });

    const abort = () => {
      status = "aborted";
      proc.kill("SIGTERM");
      setTimeout(() => { if (!proc.killed) proc.kill("SIGKILL"); }, 3000);
    };
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
  });
}

export default function teamChatExtension(pi: ExtensionAPI) {
  const runtime = loadRuntime();
  if (!runtime) return;

  const manager = runtime.members.find((item) => item.agent === runtime.manager);
  const delegates = runtime.members.filter((item) => item.agent !== runtime.manager);
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
  const queues = new Map<string, Promise<unknown>>();
  let delegationsThisRun = 0;
  let currentRoomAbort: AbortController | undefined;
  const delegationLimit = Math.max(1, runtime.max_rounds) * Math.max(1, runtime.members.length);

  const setActivity = (ctx: any) => {
    if (active.size === 0) ctx.ui.setStatus("pipal-team-activity", undefined);
    else ctx.ui.setStatus("pipal-team-activity", `team: ${[...active].map((name) => `@${name}`).join(", ")}`);
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
      const candidates = name === "team"
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

  pi.registerTool({
    name: "team_delegate",
    label: "Team message",
    description: `Send a message to a Pipal team member and receive their visible response. Available members: ${delegates.map((item) => `${item.agent} (${item.role})`).join(", ") || "none"}.`,
    promptSnippet: "Consult a member of the current Pipal team",
    promptGuidelines: [
      "Use team_delegate to obtain a real team member's view; never invent or paraphrase a consultation that did not occur.",
      "Use multiple team_delegate calls in one turn when independent parallel opinions are useful.",
      "If a member asks another member for input, route that request and return the answer to the requesting member before ending the owner turn.",
    ],
    parameters: Type.Object({
      to: Type.String({ description: "Agent name without @" }),
      message: Type.String({ description: "Clear task or message, including the context needed to respond" }),
    }),
    renderShell: "self",

    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      const initialMember = byName.get(params.to.replace(/^@/, "").toLowerCase());
      if (!initialMember || initialMember.agent === runtime.manager) {
        throw new Error(`Unknown delegate @${params.to}. Available: ${delegates.map((item) => `@${item.agent}`).join(", ")}`);
      }

      const results: MemberResult[] = [];
      const publish = (status: string) => onUpdate?.({
        content: [{ type: "text", text: status }],
        details: { results: [...results] } satisfies DelegationResult,
      });

      const runOne = async (member: RuntimeMember, from: string, message: string): Promise<MemberResult> => {
        if (delegationsThisRun >= delegationLimit) {
          throw new Error(`Team turn budget reached (${delegationLimit} agent turns).`);
        }
        delegationsThisRun += 1;
        const resultIndex = results.length;
        results.push({
          agent: member.agent,
          role: member.role,
          model: member.model,
          text: "",
          turns: 0,
          inputTokens: 0,
          outputTokens: 0,
          cost: 0,
          exitCode: -1,
          status: "thinking",
          tools: [],
        });
        const previous = queues.get(member.agent) ?? Promise.resolve();
        const operation = previous.catch(() => undefined).then(async () => {
          active.add(member.agent);
          setActivity(ctx);
          publish(`@${member.agent} is thinking…`);
          try {
            const result = await runMember(runtime, member, from, message, signal, (partial) => {
              results[resultIndex] = partial;
              publish(partial.text || `@${member.agent} is ${partial.status ?? "thinking"}…`);
            });
            results[resultIndex] = result;
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
            active.delete(member.agent);
            setActivity(ctx);
          }
        });
        queues.set(member.agent, operation);
        return operation;
      };

      const mentionsIn = (text: string, sender: string, ancestors: Set<string>): RuntimeMember[] => {
        const found: RuntimeMember[] = [];
        const seen = new Set<string>();
        for (const match of text.matchAll(/@([\w.-]+)/g)) {
          const name = match[1].toLowerCase();
          const candidates = name === "team" ? runtime.members : [byName.get(name)].filter(Boolean) as RuntimeMember[];
          for (const member of candidates) {
            if (member.agent === sender || ancestors.has(member.agent) || seen.has(member.agent)) continue;
            seen.add(member.agent);
            found.push(member);
          }
        }
        return found;
      };

      const runThread = async (
        member: RuntimeMember,
        from: string,
        message: string,
        ancestors = new Set<string>(),
      ): Promise<MemberResult> => {
        const result = await runOne(member, from, message);
        const nextAncestors = new Set(ancestors).add(member.agent);
        const mentioned = mentionsIn(result.text, member.agent, nextAncestors);
        if (mentioned.length === 0) return result;

        const replies = await Promise.all(mentioned.map((target) => runThread(
          target,
          member.agent,
          `@${member.agent} said:\n\n${result.text}\n\nYou were explicitly mentioned. Respond to @${member.agent}'s message.`,
          nextAncestors,
        )));
        const gathered = replies.map((reply) => `@${reply.agent} (${reply.role}): ${reply.text}`).join("\n\n");
        return runThread(
          member,
          "team",
          `The agents you addressed replied:\n\n${gathered}\n\nContinue your response to the owner using their input. Only @mention someone if you need another response from them.`,
          ancestors,
        );
      };

      const finalResult = await runThread(initialMember, runtime.manager, params.message);
      const conversation = results
        .filter(Boolean)
        .map((result) => `@${result.agent} (${result.role}): ${result.text || "(no response)"}`)
        .join("\n\n");
      const inputTokens = results.reduce((sum, result) => sum + (result?.inputTokens ?? 0), 0);
      const outputTokens = results.reduce((sum, result) => sum + (result?.outputTokens ?? 0), 0);
      const cost = results.reduce((sum, result) => sum + (result?.cost ?? 0), 0);
      return {
        content: [{ type: "text", text: conversation || finalResult.text || "(no response)" }],
        details: { results } satisfies DelegationResult,
        usage: {
          input: inputTokens,
          output: outputTokens,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: inputTokens + outputTokens,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: cost },
        },
      };
    },

    renderCall() {
      // Delegation is orchestration, not a visible member tool. Member tool calls
      // are rendered below with their native Pi renderers.
      return new Text("", 0, 0);
    },

    renderResult(result, { expanded }, theme) {
      const details = result.details as Partial<DelegationResult> | undefined;
      return renderAgentTools(details?.results ?? [], expanded, theme);
    },
  });

  pi.on("input", async (event, ctx) => {
    delegationsThisRun = 0;
    const text = event.text.replace(/\\@/g, "@");
    const mentioned: RuntimeMember[] = [];
    const seen = new Set<string>();
    let wholeTeam = false;
    for (const match of text.matchAll(/@([\w.-]+)/g)) {
      const name = match[1].toLowerCase();
      if (name === "team") {
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
        : manager ? [manager] : [];
    if (targets.length === 0) {
      ctx.ui.notify("This team has no available agents", "error");
      return { action: "handled" };
    }

    appendTranscript(runtime, {
      type: "message",
      author: { kind: "owner", name: runtime.owner, role: "Owner" },
      targets: targets.map((member) => member.agent),
      content: text,
    });
    pi.appendEntry("pipal-team-owner", { owner: runtime.owner, text });

    currentRoomAbort?.abort();
    currentRoomAbort = new AbortController();
    try {
      const directTargets = new Set(targets.map((target) => target.agent));
      await Promise.all(targets.map((target) => runRoomThread(
        target,
        runtime.owner,
        text,
        currentRoomAbort!.signal,
        ctx,
        new Set([...directTargets].filter((agent) => agent !== target.agent)),
      )));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      ctx.ui.notify(message, currentRoomAbort.signal.aborted ? "warning" : "error");
    } finally {
      currentRoomAbort = undefined;
      ctx.ui.setWidget("pipal-team-live-tools", undefined);
      ctx.ui.setStatus("pipal-team-activity", undefined);
    }
    return { action: "handled" };
  });

  pi.on("tool_execution_start", (event) => {
    if (event.toolName === "team_delegate") return;
    appendTranscript(runtime, readsTranscript(runtime, event.toolName, event.args) ? {
      type: "history_read",
      author: { kind: "agent", name: runtime.manager, role: manager?.role ?? "Manager" },
    } : {
      type: "tool_call",
      author: { kind: "agent", name: runtime.manager, role: manager?.role ?? "Manager" },
      tool: event.toolName,
      args: event.args,
    });
  });

  pi.on("tool_execution_end", (event) => {
    if (event.toolName === "team_delegate" || readsTranscript(runtime, event.toolName, event.args)) return;
    appendTranscript(runtime, {
      type: "tool_result",
      author: { kind: "agent", name: runtime.manager, role: manager?.role ?? "Manager" },
      tool: event.toolName,
      output: toolResultText(event.result),
      is_error: event.isError,
    });
  });

  pi.on("message_end", (event) => {
    const text = textFromMessage(event.message);
    if (!text || text.trim() === "[[PIPAL_MEMBER_ONLY]]") return;
    appendTranscript(runtime, {
      type: "message",
      author: { kind: "agent", name: runtime.manager, role: manager?.role ?? "Manager" },
      content: stripAgentPrefix(text, runtime.manager),
    });
  });

  pi.on("session_start", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
    try {
      for (const line of fs.readFileSync(runtime.transcript_file, "utf8").split("\n")) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type !== "message" || !event.author) continue;
        if (event.author.kind === "owner") {
          pi.appendEntry("pipal-team-owner", { owner: event.author.name, text: event.content });
        } else if (event.author.kind === "agent") {
          pi.appendEntry("pipal-team-agent-reply", {
            agent: event.author.name,
            role: event.author.role ?? "Member",
            text: event.content,
          });
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
    const mentionNames = new Set(["team", ...runtime.members.map((item) => item.agent.toLowerCase())]);
    ctx.ui.setEditorComponent((tui, theme, keybindings) =>
      new TeamEditor(tui, theme, keybindings, mentionNames)
    );
    ctx.ui.setHeader((_tui, theme) => ({
      render(width: number) {
        const lines = [
          theme.fg("accent", theme.bold(`PIPAL TEAM  ${runtime.team}`)),
          theme.fg("muted", `topic: ${runtime.topic}`),
          theme.fg("muted", `working directory: ${runtime.working_dir}`),
          theme.fg("muted", `owner: ${runtime.owner}`),
          theme.fg("muted", `manager: @${runtime.manager}`),
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
          { value: "@team", label: "@team", description: "Address the whole team" },
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

  pi.registerMarkdownTransformer((markdown, context) => {
    if (context.messageType === "assistant") {
      const silentMarker = "[[PIPAL_MEMBER_ONLY]]";
      const current = markdown.trim();
      if (current === silentMarker || (current.length > 0 && silentMarker.startsWith(current))) return "";
      const role = manager?.role ?? "Manager";
      return `**@${runtime.manager} (${role}):** ${markdown}`;
    }
    if (context.messageType === "user") {
      const routed = markdown.match(/^\[\[PIPAL_TEAM_ROUTE:([^\]]+)\]\]\nOwner message: ([\s\S]*?)\nRouting instruction:/);
      const visible = routed ? `@${routed[1]} ${routed[2]}` : markdown;
      return `**${runtime.owner} (Owner)**\n\n${visible}`;
    }
    return markdown;
  });
}
