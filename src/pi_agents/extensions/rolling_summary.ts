import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";

type ContentBlock = {
  type?: string;
  text?: string;
  name?: string;
  arguments?: Record<string, unknown>;
};

type SessionEntry = {
  type: string;
  message?: {
    role?: string;
    content?: unknown;
  };
};

const SUMMARY_FILE_NAME = "summary.md";

const extractTextParts = (content: unknown): string[] => {
  if (typeof content === "string") return [content];
  if (!Array.isArray(content)) return [];

  const parts: string[] = [];
  for (const part of content) {
    if (!part || typeof part !== "object") continue;
    const block = part as ContentBlock;
    if (block.type === "text" && typeof block.text === "string") {
      parts.push(block.text);
    }
  }
  return parts;
};

const extractToolCallLines = (content: unknown): string[] => {
  if (!Array.isArray(content)) return [];
  const toolCalls: string[] = [];
  for (const part of content) {
    if (!part || typeof part !== "object") continue;
    const block = part as ContentBlock;
    if (block.type !== "toolCall" || typeof block.name !== "string") continue;
    const args = block.arguments ?? {};
    toolCalls.push(`Tool ${block.name} called with args ${JSON.stringify(args)}`);
  }
  return toolCalls;
};

const buildConversationText = (entries: SessionEntry[]): string => {
  const sections: string[] = [];

  for (const entry of entries) {
    if (entry.type !== "message" || !entry.message?.role) continue;
    const role = entry.message.role;
    const isUser = role === "user";
    const isAssistant = role === "assistant";
    if (!isUser && !isAssistant) continue;

    const lines: string[] = [];
    const textParts = extractTextParts(entry.message.content);
    if (textParts.length > 0) {
      const roleLabel = isUser ? "User" : "Assistant";
      const messageText = textParts.join("\n").trim();
      if (messageText.length > 0) {
        lines.push(`${roleLabel}: ${messageText}`);
      }
    }

    if (isAssistant) {
      lines.push(...extractToolCallLines(entry.message.content));
    }

    if (lines.length > 0) sections.push(lines.join("\n"));
  }

  return sections.join("\n\n");
};

const resolveSummaryPath = (sessionFile?: string | null): string | undefined => {
  if (!sessionFile) return undefined;
  return path.join(path.dirname(sessionFile), SUMMARY_FILE_NAME);
};

const loadSummary = (summaryPath: string): string => {
  if (!fs.existsSync(summaryPath)) return "";
  return fs.readFileSync(summaryPath, "utf-8");
};

const ensureSummaryFile = (summaryPath: string) => {
  if (fs.existsSync(summaryPath)) return;
  fs.mkdirSync(path.dirname(summaryPath), { recursive: true });
  fs.writeFileSync(summaryPath, "", "utf-8");
};

const logSummaryEvent = (summaryPath: string, message: string) => {
  const logPath = path.join(path.dirname(summaryPath), "summary.log");
  const line = `[${new Date().toISOString()}] ${message}\n`;
  fs.appendFileSync(logPath, line, "utf-8");
};

const resolveAgentName = () => {
  const agentDir = process.env.PAL_AGENT_DIR;
  if (!agentDir) return undefined;
  return path.basename(agentDir);
};

const resolveSessionName = (sessionFile?: string | null) => {
  if (!sessionFile) return undefined;
  const sessionDir = path.dirname(sessionFile);
  return path.basename(sessionDir);
};

export default function (pi: ExtensionAPI) {
  const writeSummary = async (ctx: ExtensionContext) => {
    const sessionFile = ctx.sessionManager.getSessionFile();
    const summaryPath = resolveSummaryPath(sessionFile);
    if (!summaryPath) return;

    const entries = ctx.sessionManager.getBranch();
    const conversationText = buildConversationText(entries as SessionEntry[]);
    if (!conversationText.trim()) return;

    const agentName = resolveAgentName();
    const sessionName = resolveSessionName(sessionFile);
    if (!agentName || !sessionName) {
      logSummaryEvent(summaryPath, "Summarize skipped (missing agent/session name)");
      if (ctx.hasUI) ctx.ui.notify("Rolling summary: skipped (missing agent/session)", "warning");
      return;
    }

    logSummaryEvent(summaryPath, `Summarize start via CLI agent=${agentName} session=${sessionName}`);

    const spinnerFrames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
    let spinner: ReturnType<typeof setInterval> | undefined;
    if (ctx.hasUI) {
      let i = 0;
      const render = () =>
        ctx.ui.setWidget("rolling-summary", (tui, theme) => {
          const text = theme.fg("warning", `${spinnerFrames[i]} Updating rolling summary...`);
          return new Text(text, 0, 0);
        });

      render();
      spinner = setInterval(() => {
        i = (i + 1) % spinnerFrames.length;
        render();
      }, 120);
    }

    try {
      const result = await pi.exec("pal", [
        "session",
        "summarize",
        "--agent",
        agentName,
        "--session",
        sessionName,
      ]);

      if (result.code !== 0) {
        const err = result.stderr?.trim() || result.stdout?.trim() || "Unknown error";
        logSummaryEvent(summaryPath, `Summarize failed error=${err}`);
        if (ctx.hasUI) ctx.ui.notify("Rolling summary: failed (see summary.log)", "error");
        return;
      }

      const out = result.stdout?.trim() || "";
      logSummaryEvent(summaryPath, `Summarize complete ${out}`);
      if (ctx.hasUI) ctx.ui.notify(`Rolling summary updated: ${summaryPath}`, "info");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      logSummaryEvent(summaryPath, `Summarize failed error=${message}`);
      if (ctx.hasUI) ctx.ui.notify("Rolling summary: failed (see summary.log)", "error");
    } finally {
      if (spinner) clearInterval(spinner);
      if (ctx.hasUI) ctx.ui.setWidget("rolling-summary", undefined);
    }
  };

  pi.on("session_start", async (_event, ctx) => {
    const sessionFile = ctx.sessionManager.getSessionFile();
    const summaryPath = resolveSummaryPath(sessionFile);
    if (!summaryPath) return;

    ensureSummaryFile(summaryPath);
    logSummaryEvent(summaryPath, "Summary file ready");
    if (ctx.hasUI) ctx.ui.notify(`Rolling summary file ready: ${summaryPath}`, "info");

    const summary = loadSummary(summaryPath).trim();
    if (!summary) return;

    ctx.sessionManager.appendCustomMessageEntry(
      "pal-rolling-summary",
      summary,
      false,
      { summaryPath }
    );

    ctx.sessionManager.appendCustomMessageEntry(
      "pal-rolling-summary-banner",
      "Loaded rolling summary for this agent. Prior sessions are summarized in summary.md.",
      true,
      { summaryPath }
    );
  });

  pi.on("turn_end", async (_event, ctx) => {
    if (ctx.hasUI) return; // print/json mode
    await writeSummary(ctx);
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    await writeSummary(ctx);
  });
}
