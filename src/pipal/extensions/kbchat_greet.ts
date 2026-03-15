import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const INTRO_GREET_INSTRUCTION =
  "Begin the conversation now. Greet the user briefly as Erklär‑Erwin. If no KB path is set, ask for it. If it is set, acknowledge it and invite a question.";

const RETURN_GREET_INSTRUCTION =
  "Begin the conversation now. Greet the user briefly as Erklär‑Erwin. If no KB path is set, ask for it. If it is set, acknowledge it and invite a question.";

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

function readKbPath(agentDir?: string | null): string {
  if (!agentDir) return "";
  const kbPath = path.join(agentDir, "KB.md");
  try {
    const content = fs.readFileSync(kbPath, "utf-8");
    const match = content.match(/Path:\s*(.*)/i);
    return match ? match[1].trim() : "";
  } catch {
    return "";
  }
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

    const kbPath = readKbPath(agentDir);

    const options = ctx.isIdle()
      ? { triggerTurn: true }
      : { deliverAs: "followUp" as const, triggerTurn: true };

    const instruction = firstEver ? INTRO_GREET_INSTRUCTION : RETURN_GREET_INSTRUCTION;
    const content = `${instruction}\n\nKB path: ${kbPath || "(not set)"}`;

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
}
