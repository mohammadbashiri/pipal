import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

type ContentBlock = {
  type?: string;
  text?: string;
  name?: string;
  arguments?: Record<string, unknown>;
};

type SessionEntry = {
  type: string;
  timestamp?: string | number;
  message?: {
    role?: string;
    content?: unknown;
    timestamp?: string | number;
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
  const agentDir = process.env.PIPAL_AGENT_DIR;
  if (!agentDir) return undefined;
  return path.basename(agentDir);
};

const resolveSessionName = (sessionFile?: string | null) => {
  if (!sessionFile) return undefined;
  const sessionDir = path.dirname(sessionFile);
  return path.basename(sessionDir);
};

const resolveEntryTimestamp = (entry: SessionEntry): string | undefined => {
  const raw = entry.timestamp ?? entry.message?.timestamp;
  if (raw === undefined || raw === null) return undefined;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return String(raw);
  return date.toISOString();
};

const RECENT_MESSAGES_DEFAULT = 40;

const resolveRecentMessagesLimit = () => {
  const raw = process.env.PIPAL_RECENT_MESSAGES;
  const parsed = raw ? Number.parseInt(raw, 10) : RECENT_MESSAGES_DEFAULT;
  if (!Number.isFinite(parsed) || parsed <= 0) return RECENT_MESSAGES_DEFAULT;
  return parsed;
};

const findPreviousSessionFile = (sessionFile?: string | null): string | undefined => {
  if (!sessionFile) return undefined;
  const sessionDir = path.dirname(sessionFile);
  if (!fs.existsSync(sessionDir)) return undefined;

  const files = fs
    .readdirSync(sessionDir)
    .filter((name) => name.endsWith(".jsonl"))
    .map((name) => path.join(sessionDir, name))
    .filter((filePath) => path.resolve(filePath) !== path.resolve(sessionFile))
    .sort((a, b) => b.localeCompare(a));

  return files[0];
};

const loadRecentMessages = (sessionPath: string, limit: number): string => {
  if (!fs.existsSync(sessionPath)) return "";

  let raw: string;
  try {
    raw = fs.readFileSync(sessionPath, "utf-8");
  } catch {
    return "";
  }

  const lines = raw.split(/\r?\n/).filter(Boolean);
  const messages: string[] = [];

  for (let i = lines.length - 1; i >= 0 && messages.length < limit; i -= 1) {
    let entry: SessionEntry | undefined;
    try {
      entry = JSON.parse(lines[i]);
    } catch {
      continue;
    }

    if (entry?.type !== "message") continue;
    const role = entry.message?.role;
    if (role !== "user" && role !== "assistant") continue;

    const textParts = extractTextParts(entry.message?.content);
    const messageText = textParts.join("\n").trim();
    if (!messageText) continue;

    const roleLabel = role === "user" ? "User" : "Assistant";
    const ts = resolveEntryTimestamp(entry);
    const tsLabel = ts ? ` (${ts})` : "";
    messages.push(`${roleLabel}${tsLabel}: ${messageText}`);
  }

  return messages.reverse().join("\n\n");
};

const loadLastEntryType = (sessionPath?: string | null): string | undefined => {
  if (!sessionPath || !fs.existsSync(sessionPath)) return undefined;
  let raw: string;
  try {
    raw = fs.readFileSync(sessionPath, "utf-8");
  } catch {
    return undefined;
  }
  const lines = raw.split(/\r?\n/).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    try {
      const entry = JSON.parse(lines[i]);
      return entry?.type;
    } catch {
      continue;
    }
  }
  return undefined;
};

export default function (pi: ExtensionAPI) {
  let summarizedThisSession = false;

  const writeSummary = async (ctx: ExtensionContext) => {
    const sessionFile = ctx.sessionManager.getSessionFile();
    const summaryPath = resolveSummaryPath(sessionFile);
    if (!summaryPath) return;

    const agentName = resolveAgentName();
    const sessionName = resolveSessionName(sessionFile);
    if (!agentName || !sessionName) {
      logSummaryEvent(summaryPath, "Summarize skipped (missing agent/session name)");
      if (ctx.hasUI) ctx.ui.notify("Rolling summary: skipped (missing agent/session)", "warning");
      return;
    }

    const hasMessages = ctx
      .sessionManager
      .getEntries()
      .some((entry: SessionEntry) =>
        entry.type === "message" &&
        (entry.message?.role === "user" || entry.message?.role === "assistant")
      );
    if (!hasMessages) {
      logSummaryEvent(summaryPath, "Summarize skipped (no messages)");
      return;
    }

    logSummaryEvent(summaryPath, `Summarize start via CLI agent=${agentName} session=${sessionName}`);

    const spinnerFrames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
    let spinnerIndex = 0;
    let spinnerLabel = "Compacting...";
    let spinner: ReturnType<typeof setInterval> | undefined;

    const clearLine = () => process.stdout.write("\r\x1b[K");

    if (ctx.hasUI) {
      process.stdout.write(`${spinnerFrames[0]} ${spinnerLabel}`);
      spinner = setInterval(() => {
        spinnerIndex = (spinnerIndex + 1) % spinnerFrames.length;
        process.stdout.write(`\r${spinnerFrames[spinnerIndex]} ${spinnerLabel}`);
      }, 120);
    }

    try {
      const lastEntryType = loadLastEntryType(sessionFile);
      if (lastEntryType !== "compaction") {
        logSummaryEvent(summaryPath, "Compaction start (session shutdown)");
        await new Promise<void>((resolve, reject) => {
          ctx.compact({
            onComplete: () => resolve(),
            onError: (error) => reject(error),
          });
        });
        logSummaryEvent(summaryPath, "Compaction complete (session shutdown)");
      }

      if (ctx.hasUI) {
        spinnerLabel = "Updating summary...";
      }

      const result = await pi.exec("pipal", [
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
        if (ctx.hasUI) {
          clearInterval(spinner);
          clearLine();
          process.stdout.write("✗ Rolling summary failed\r\n");
        }
        return;
      }

      const out = result.stdout?.trim() || "";
      logSummaryEvent(summaryPath, `Summarize complete ${out}`);
      if (ctx.hasUI) {
        clearInterval(spinner);
        clearLine();
        process.stdout.write("✓ Rolling summary updated\r\n");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      logSummaryEvent(summaryPath, `Summarize failed error=${message}`);
      if (ctx.hasUI) {
        clearInterval(spinner);
        clearLine();
        process.stdout.write("✗ Rolling summary failed\r\n");
      }
    } finally {
      if (spinner) clearInterval(spinner);
    }
  };

  const rawConfirm = (question: string): Promise<boolean> => {
    return new Promise((resolve) => {
      process.stdout.write(`\r\n${question} [y/N]: `);

      let finished = false;
      const wasRaw = (process.stdin as NodeJS.ReadStream & { isRaw?: boolean }).isRaw ?? false;

      const cleanup = () => {
        process.stdin.removeListener("data", onData);
        try {
          if (!wasRaw) (process.stdin as NodeJS.ReadStream).setRawMode(false);
          process.stdin.pause();
        } catch {
          // ignore
        }
      };

      const finish = (answer: boolean) => {
        if (finished) return;
        finished = true;
        process.stdout.write(`${answer ? "y" : "N"}\r\n`);
        clearTimeout(timer);
        cleanup();
        resolve(answer);
      };

      const onData = (chunk: Buffer | string) => {
        const first = chunk.toString("utf8")[0] ?? "";
        finish(first === "y" || first === "Y");
      };

      const timer = setTimeout(() => finish(false), 15000);

      try {
        (process.stdin as NodeJS.ReadStream).setRawMode(true);
        process.stdin.resume();
        process.stdin.on("data", onData);
      } catch {
        clearTimeout(timer);
        resolve(false);
      }
    });
  };

  const handleSummaryOnExit = async (ctx: ExtensionContext) => {
    const sessionFile = ctx.sessionManager.getSessionFile();
    const summaryPath = resolveSummaryPath(sessionFile);

    const hasMessages = ctx
      .sessionManager
      .getEntries()
      .some((entry: SessionEntry) =>
        entry.type === "message" &&
        (entry.message?.role === "user" || entry.message?.role === "assistant")
      );

    if (!ctx.hasUI || !hasMessages) {
      await writeSummary(ctx);
      return;
    }

    const confirmed = await rawConfirm("Update rolling summary?");

    if (!confirmed) {
      if (summaryPath) {
        logSummaryEvent(summaryPath, "Summarize skipped (user declined)");
      }
      return;
    }

    await writeSummary(ctx);
  };

  pi.on("session_start", async (_event, ctx) => {
    summarizedThisSession = false;
    const sessionFile = ctx.sessionManager.getSessionFile();
    const summaryPath = resolveSummaryPath(sessionFile);
    if (!summaryPath) return;

    ensureSummaryFile(summaryPath);
    logSummaryEvent(summaryPath, "Summary file ready");

    const previousSession = findPreviousSessionFile(sessionFile);
    if (!previousSession) return;

    const limit = resolveRecentMessagesLimit();
    const recentText = loadRecentMessages(previousSession, limit);
    if (!recentText) return;

    ctx.sessionManager.appendCustomMessageEntry(
      "pipal-recent-messages",
      `Recent messages from previous session:\n\n${recentText}`,
      false,
      { sourceSession: path.basename(previousSession), limit }
    );
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    if (summarizedThisSession) return;
    await handleSummaryOnExit(ctx);
  });

}
