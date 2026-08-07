import { spawn } from "node:child_process";
import * as fs from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { CustomEditor, getMarkdownTheme } from "@earendil-works/pi-coding-agent";
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
      const match = text.match(/^@([\w.-]+)\s+/);
      if (match && this.mentionNames.has(match[1].toLowerCase())) {
        // Pi reserves @... for file expansion. Escape known team mentions only at
        // submission time; the editor and rendered owner message remain clean.
        this.setText(`\\${text}`);
      }
    }
    super.handleInput(data);
  }
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

function textFromMessage(message: any): string {
  if (!message || message.role !== "assistant" || !Array.isArray(message.content)) return "";
  return message.content
    .filter((part: any) => part?.type === "text" && typeof part.text === "string")
    .map((part: any) => part.text)
    .join("\n")
    .trim();
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
    "",
    message,
    "",
    `Respond as @${member.agent}, the ${member.role}. Give your independent contribution to the shared discussion.`,
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
      cwd: member.agent_path,
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
        status = `using ${event.toolName ?? "tool"}`;
        onProgress(snapshot());
      } else if (event.type === "message_end" && event.message?.role === "assistant") {
        const current = textFromMessage(event.message);
        if (current) finalText = current;
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

function formatTokens(value: number): string {
  if (value < 1000) return String(value);
  return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}k`;
}

export default function teamChatExtension(pi: ExtensionAPI) {
  const runtime = loadRuntime();
  if (!runtime) return;

  const manager = runtime.members.find((item) => item.agent === runtime.manager);
  const delegates = runtime.members.filter((item) => item.agent !== runtime.manager);
  const byName = new Map(runtime.members.map((item) => [item.agent.toLowerCase(), item]));
  const active = new Set<string>();
  const queues = new Map<string, Promise<unknown>>();
  let delegationsThisRun = 0;
  const delegationLimit = Math.max(1, runtime.max_rounds) * Math.max(1, delegates.length);

  const setActivity = (ctx: any) => {
    if (active.size === 0) ctx.ui.setStatus("pipal-team-activity", undefined);
    else ctx.ui.setStatus("pipal-team-activity", `team: ${[...active].map((name) => `@${name}`).join(", ")}`);
  };

  pi.registerTool({
    name: "team_delegate",
    label: "Team message",
    description: `Send a message to a Pipal team member and receive their visible response. Available members: ${delegates.map((item) => `${item.agent} (${item.role})`).join(", ") || "none"}.`,
    promptSnippet: "Consult a member of the current Pipal team",
    promptGuidelines: [
      "Use team_delegate to obtain a real team member's view; never invent or paraphrase a consultation that did not occur.",
      "Use multiple team_delegate calls in one turn when independent parallel opinions are useful.",
    ],
    parameters: Type.Object({
      to: Type.String({ description: "Agent name without @" }),
      message: Type.String({ description: "Clear task or message, including the context needed to respond" }),
    }),
    renderShell: "self",

    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      const member = byName.get(params.to.replace(/^@/, "").toLowerCase());
      if (!member || member.agent === runtime.manager) {
        throw new Error(`Unknown delegate @${params.to}. Available: ${delegates.map((item) => `@${item.agent}`).join(", ")}`);
      }
      if (delegationsThisRun >= delegationLimit) {
        throw new Error(`Team turn budget reached (${delegationLimit} delegations). Synthesize or ask the owner to continue.`);
      }
      delegationsThisRun += 1;

      const previous = queues.get(member.agent) ?? Promise.resolve();
      const operation = previous.catch(() => undefined).then(async () => {
        active.add(member.agent);
        setActivity(ctx);
        onUpdate?.({
          content: [{ type: "text", text: `@${member.agent} is thinking…` }],
          details: { agent: member.agent, role: member.role, model: member.model, status: "thinking" },
        });
        try {
          const result = await runMember(runtime, member, runtime.manager, params.message, signal, (partial) => {
            onUpdate?.({
              content: [{ type: "text", text: partial.text || `@${member.agent} is ${partial.status ?? "thinking"}…` }],
              details: partial,
            });
          });
          return {
            content: [{ type: "text", text: result.text || "(no response)" }],
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
        } finally {
          active.delete(member.agent);
          setActivity(ctx);
        }
      });
      queues.set(member.agent, operation);
      return operation;
    },

    renderCall(args, theme) {
      const name = String(args.to ?? "member").replace(/^@/, "");
      const member = byName.get(name.toLowerCase());
      const label = member ? `${member.role}${member.model ? ` · ${member.model}` : ""}` : "team member";
      return new Text(
        `${theme.fg("accent", theme.bold(`@${name}`))} ${theme.fg("muted", label)}\n${theme.fg("dim", String(args.message ?? ""))}`,
        1,
        0,
      );
    },

    renderResult(result, { isPartial }, theme) {
      const details = result.details as Partial<MemberResult> | undefined;
      const name = details?.agent ?? "member";
      const role = details?.role ?? "Team member";
      const model = details?.model ? ` · ${details.model}` : "";
      const box = new Box(1, 1, (text) => theme.bg("customMessageBg", text));
      const container = new Container();
      const state = isPartial ? ` ${theme.fg("warning", details?.status ?? "thinking")}` : "";
      container.addChild(new Text(`${theme.fg("accent", theme.bold(`@${name}`))} ${theme.fg("muted", `${role}${model}`)}${state}`, 0, 0));
      container.addChild(new Spacer(1));
      const body = result.content.find((part) => part.type === "text");
      container.addChild(new Markdown(body?.type === "text" ? body.text : "(no response)", 0, 0, getMarkdownTheme()));
      if (!isPartial && details) {
        const stats = [
          details.turns ? `${details.turns} turn${details.turns === 1 ? "" : "s"}` : "",
          details.inputTokens ? `↑${formatTokens(details.inputTokens)}` : "",
          details.outputTokens ? `↓${formatTokens(details.outputTokens)}` : "",
          details.cost ? `$${details.cost.toFixed(4)}` : "",
        ].filter(Boolean).join(" ");
        if (stats) {
          container.addChild(new Spacer(1));
          container.addChild(new Text(theme.fg("dim", stats), 0, 0));
        }
      }
      box.addChild(container);
      return box;
    },
  });

  pi.on("input", (event) => {
    if (event.source === "interactive") delegationsThisRun = 0;
    const match = event.text.match(/^\\?@([\w.-]+)\s+([\s\S]+)/);
    if (!match) return { action: "continue" };
    const target = match[1];
    const body = match[2];
    const member = byName.get(target.toLowerCase());
    if (target.toLowerCase() !== "team" && !member) return { action: "continue" };

    let instruction: string;
    if (target.toLowerCase() === "team") {
      instruction = "Consult the relevant members with team_delegate, then synthesize the discussion.";
    } else if (member?.agent === runtime.manager) {
      instruction = `The owner directly addressed you, @${runtime.manager}; answer directly unless delegation would materially help.`;
    } else {
      instruction = `You MUST use team_delegate to send this message to @${member!.agent}, then return their response with only necessary manager context.`;
    }
    return {
      action: "transform",
      text: `[[PIPAL_TEAM_ROUTE:${target}]]\nOwner message: ${body}\nRouting instruction: ${instruction}`,
    };
  });

  pi.on("session_start", (_event, ctx) => {
    if (ctx.mode !== "tui") return;
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
      const role = manager?.role ?? "Manager";
      const model = manager?.model ? ` · ${manager.model}` : "";
      return `**@${runtime.manager} · ${role}${model}**\n\n${markdown}`;
    }
    if (context.messageType === "user") {
      const routed = markdown.match(/^\[\[PIPAL_TEAM_ROUTE:([^\]]+)\]\]\nOwner message: ([\s\S]*?)\nRouting instruction:/);
      const visible = routed ? `@${routed[1]} ${routed[2]}` : markdown;
      return `**${runtime.owner} · Owner**\n\n${visible}`;
    }
    return markdown;
  });
}
