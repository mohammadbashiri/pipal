import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const INTRO_GREET_INSTRUCTION =
  "Begin the conversation now. Greet the user briefly as Erklär‑Erwin and ask for the knowledge base path you should use.";

const RETURN_GREET_INSTRUCTION =
  "Begin the conversation now. Greet the user briefly as Erklär‑Erwin and ask for the knowledge base path you should use.";

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

    const options = ctx.isIdle()
      ? { triggerTurn: true }
      : { deliverAs: "followUp" as const, triggerTurn: true };

    pi.sendMessage(
      {
        customType: "pipal-autogreet",
        content: firstEver ? INTRO_GREET_INSTRUCTION : RETURN_GREET_INSTRUCTION,
        display: false,
      },
      options
    );

    if (firstEver) {
      markInitialized(agentDir);
    }
  });
}
