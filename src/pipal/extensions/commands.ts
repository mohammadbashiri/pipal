import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Conversational shortcuts only. Persistence belongs to ordinary agent tools. */
export function registerSummary(pi: ExtensionAPI) {
  pi.registerCommand("pipal:summary", {
    description: "Ask for a summary of this conversation (does not automatically save or compact)",
    handler: async (args, _ctx) => {
      const focus = args.trim();
      pi.sendUserMessage(`Summarize our conversation so far.${focus ? ` Focus on: ${focus}` : ""}`, { deliverAs: "followUp" });
    },
  });
}

// Keep one stable extension entry point: existing TUI argv can gain session
// capabilities through /reload, without restarting or adding CLI extensions.
export default async function (pi: ExtensionAPI) {
  registerSummary(pi);
  const { default: sessionBridge } = await import("./session_bridge.ts");
  sessionBridge(pi);
}
