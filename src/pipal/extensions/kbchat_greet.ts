import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const GREET_INSTRUCTION_KB_READY = (kbName: string) =>
  `Greet the user now with exactly: "Hey, how can I help you with the ${kbName}?" Nothing else.`;
const GREET_INSTRUCTION_KB_MISSING =
  "Greet the user briefly, then tell them the knowledge base path is configured but the files were not found.";
const GREET_INSTRUCTION_KB_UNCONFIGURED =
  "Greet the user briefly, then tell them no knowledge base is configured yet.";

function readKbConfig(agentDir?: string | null): { name?: string; path?: string } {
  if (!agentDir) return {};
  const kbPath = path.join(agentDir, "KB.md");
  try {
    const content = fs.readFileSync(kbPath, "utf-8");
    const nameMatch = content.match(/Name:\s*(.*)/i);
    const pathMatch = content.match(/Path:\s*(.*)/i);
    return {
      name: nameMatch ? nameMatch[1].trim() : undefined,
      path: pathMatch ? pathMatch[1].trim() : undefined,
    };
  } catch {
    return {};
  }
}

function hasGermanPreference(entries: any[]): boolean {
  return entries.some(
    (entry) =>
      entry?.type === "custom_message" &&
      entry?.customType === "pipal-lang" &&
      entry?.content === "de"
  );
}

function recordGermanPreference(pi: ExtensionAPI) {
  pi.sendMessage(
    {
      customType: "pipal-lang",
      content: "de",
      display: false,
    },
    { triggerTurn: false }
  );
}

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    if (process.env.PIPAL_DISABLE_AUTOGREET === "1") return;

    const agentDir = process.env.PIPAL_AGENT_DIR;

    const entries = ctx.sessionManager.getEntries();
    const hasMessages = entries.some((entry) => entry.type === "message");
    const hasGreet = entries.some(
      (entry) =>
        entry.type === "custom_message" &&
        (entry.customType === "pipal-autogreet" || entry.customType === "pal-autogreet")
    );

    if (hasMessages || hasGreet) return;

    const kbConfig = readKbConfig(agentDir);
    const kbPath = kbConfig.path || "";
    const kbName = kbConfig.name || "knowledge base";
    const hasPath = Boolean(kbPath);
    const kbExists = hasPath && fs.existsSync(kbPath);

    const options = ctx.isIdle()
      ? { triggerTurn: true }
      : { deliverAs: "followUp" as const, triggerTurn: true };

    let instruction: string;
    if (hasPath && kbExists) {
      instruction = GREET_INSTRUCTION_KB_READY(kbName);
    } else if (hasPath && !kbExists) {
      instruction = GREET_INSTRUCTION_KB_MISSING;
    } else {
      instruction = GREET_INSTRUCTION_KB_UNCONFIGURED;
    }
    const content = instruction;

    pi.sendMessage(
      {
        customType: "pipal-autogreet",
        content,
        display: false,
      },
      options
    );
  });

  pi.on("message_end", async (event, ctx) => {
    const role = event?.message?.role;
    if (role !== "user") return;

    const content = event?.message?.content;
    const normalized = typeof content === "string" ? content.toLowerCase() : "";
    if (!normalized) return;

    if (!/(\bdeutsch\b|\bgerman\b|\bauf deutsch\b)/i.test(normalized)) return;

    const entries = ctx.sessionManager.getEntries();
    if (hasGermanPreference(entries)) return;

    recordGermanPreference(pi);
  });
}
