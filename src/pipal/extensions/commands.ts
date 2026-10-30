import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Conversational shortcuts only. Persistence belongs to ordinary agent tools. */
export default function (pi: ExtensionAPI) {
  pi.registerCommand("pipal:summary", {
    description: "Ask for a summary of this conversation (does not automatically save or compact)",
    handler: async (args, _ctx) => {
      const focus = args.trim();
      pi.sendUserMessage(`Summarize our conversation so far.${focus ? ` Focus on: ${focus}` : ""}`, { deliverAs: "followUp" });
    },
  });
}
