import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const INTRO_GREET_INSTRUCTION =
  "Begin the conversation now. Say you just came online and are excited to meet them. Briefly introduce yourself and ask whether they want to keep your current name or give you a different one. Then ask what they want to be called. Keep it short (one or two questions). Avoid jumping into work topics yet.";

const RETURN_GREET_INSTRUCTION =
  "Begin the conversation now. Greet the user briefly as someone you already know. Do not re-introduce yourself or ask for names. Ask what they'd like to do or talk about.";

function isFirstEver(agentDir?: string | null) {
  if (!agentDir) return true;
  const marker = path.join(agentDir, ".pal_initialized");
  return !fs.existsSync(marker);
}

function markInitialized(agentDir?: string | null) {
  if (!agentDir) return;
  const marker = path.join(agentDir, ".pal_initialized");
  if (!fs.existsSync(marker)) {
    fs.writeFileSync(marker, "initialized\n", "utf-8");
  }
}

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    if (process.env.PAL_DISABLE_AUTOGREET === "1") return;

    const agentDir = process.env.PAL_AGENT_DIR;
    const firstEver = isFirstEver(agentDir);

    const entries = ctx.sessionManager.getEntries();
    const hasMessages = entries.some((entry) => entry.type === "message");
    const hasGreet = entries.some(
      (entry) => entry.type === "custom_message" && entry.customType === "pal-autogreet"
    );

    if (hasMessages || hasGreet) return;

    const options = ctx.isIdle()
      ? { triggerTurn: true }
      : { deliverAs: "followUp" as const, triggerTurn: true };

    pi.sendMessage(
      {
        customType: "pal-autogreet",
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
