import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const INTRO_GREET_INSTRUCTION =
  "Begin the conversation now. Greet the user briefly as Erklär‑Erwin in English. If no KB is configured or it is missing, ask the user to set it. If it is configured, say: 'Hey, how can I help you with the [KB NAME]?' Do not mention filesystem paths or internal locations. Add: 'I can also speak German if you prefer that.'";

const RETURN_GREET_INSTRUCTION =
  "Begin the conversation now. Greet the user briefly as Erklär‑Erwin in English. If no KB is configured or it is missing, ask the user to set it. If it is configured, say: 'Hey, how can I help you with the [KB NAME]?' Do not mention filesystem paths or internal locations. Add: 'I can also speak German if you prefer that.'";

function resolveInitMarker(agentDir?: string | null) {
  if (!agentDir) return undefined;
  const newMarker = path.join(agentDir, ".pipal_initialized");
  const oldMarker = path.join(agentDir, ".pal_initialized");

  if (fs.existsSync(newMarker)) return newMarker;
  if (fs.existsSync(oldMarker)) return oldMarker;
  return newMarker;
}

function isFirstEver(agentDir?: string | null) {
  const marker = resolveInitMarker(agentDir);
  if (!marker) return true;
  return !fs.existsSync(marker);
}

function markInitialized(agentDir?: string | null) {
  const marker = resolveInitMarker(agentDir);
  if (!marker) return;
  if (!fs.existsSync(marker)) {
    fs.writeFileSync(marker, "initialized\n", "utf-8");
  }
}

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
    const firstEver = isFirstEver(agentDir);

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

    const instruction = firstEver ? INTRO_GREET_INSTRUCTION : RETURN_GREET_INSTRUCTION;
    let kbLine = "KB is not configured";
    if (hasPath && kbExists) {
      kbLine = `KB name: ${kbName}`;
    } else if (hasPath && !kbExists) {
      kbLine = "KB path is configured but not found";
    }
    const content = `${instruction}\n\n${kbLine}\n\nKB NAME: ${kbName}`;

    pi.sendMessage(
      {
        customType: "pipal-autogreet",
        content,
        display: false,
      },
      options
    );

    if (firstEver) {
      markInitialized(agentDir);
    }
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
