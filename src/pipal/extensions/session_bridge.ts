import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import liveSessions from "./live_sessions.ts";
import sessionTools from "./session_tools.ts";

// Extension API objects differ, but their scoped event facades share the native
// runtime bus. Claim synchronously so global + Pipal + explicit loads initialize
// one socket/router. Native reload disposes subscriptions; no process singleton.
const channel = "pipal:session-capabilities:claim";
export default function sessionBridge(pi: ExtensionAPI) {
  const claim = { claimed: false };
  pi.events.emit(channel, claim);
  if (claim.claimed) return;
  const unsubscribe = pi.events.on(channel, (other: { claimed: boolean }) => { other.claimed = true; });
  pi.on("session_shutdown", () => unsubscribe());
  liveSessions(pi);
  sessionTools(pi);
}
