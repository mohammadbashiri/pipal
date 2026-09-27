"""Optional local bridge between ClickClack bot identities and Pipal agents."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .llm_config import load_llm_config
from .registry import get_agent
from .runner import run_agent_print


def _request(base: str, path: str, token: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{base.rstrip('/')}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _context_packet(base: str, token: str, channel_id: str, message_id: str) -> tuple[str, str]:
    message = _request(base, f"/api/messages/{message_id}", token)["message"]
    page = _request(base, f"/api/channels/{channel_id}/messages?limit=12", token)
    events = []
    for item in page.get("messages", []):
        author = item.get("author", {}).get("display_name", "Participant")
        events.append(f"{author}: {item.get('body', '')}")
    return message.get("body", ""), "\n".join(events[-12:])


def _reply(base: str, token: str, channel_id: str, text: str) -> None:
    _request(base, f"/api/channels/{channel_id}/messages", token, "POST", {"body": text})


def _typing(base: str, token: str, workspace_id: str, channel_id: str, turn_id: str, started: bool) -> None:
    _request(base, "/api/realtime/ephemeral", token, "POST", {
        "workspace_id": workspace_id,
        "channel_id": channel_id,
        "type": "typing.started" if started else "typing.stopped",
        "payload": {"turn_id": turn_id},
    })


def run_clickclack_bridge(config_path: Path) -> None:
    from websockets.sync.client import connect

    config = json.loads(config_path.read_text(encoding="utf-8"))
    base, workspace = config["base_url"], config["workspace_id"]
    state_path = config_path.with_suffix(".state.json")
    try:
        cursor = json.loads(state_path.read_text()).get("cursor", "")
    except (OSError, json.JSONDecodeError):
        cursor = ""
    bots = {item["bot_user_id"]: item for item in config["agents"]}
    poll_token = next(iter(bots.values()))["token"]
    # A first start begins at the current tail; old messages are not replayed.
    if not cursor:
        cursor = _request(base, f"/api/realtime/events?workspace_id={workspace}&include_tail=true", poll_token).get("tail_cursor", "")
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    print(f"ClickClack bridge connected: {len(bots)} Pipal agent(s). Ctrl+C to stop.")
    while True:
        try:
            url = f"{ws_base.rstrip('/')}/api/realtime/ws?workspace_id={workspace}&after_cursor={cursor}"
            with connect(url, additional_headers={"Authorization": f"Bearer {poll_token}"}, open_timeout=10) as socket:
                for raw_event in socket:
                    event = json.loads(raw_event)
                    cursor = event.get("cursor", cursor)
                    state_path.write_text(json.dumps({"cursor": cursor}) + "\n", encoding="utf-8")
                    if event.get("type") != "message.created" or not event.get("channel_id"):
                        continue
                    author = event.get("payload", {}).get("author_id")
                    targets = [bots[item] for item in event.get("mentioned_user_ids", []) if item in bots]
                    # ClickClack resolves named bot mentions; these are Pipal
                    # channel conveniences that fan out to all mapped bot users.
                    message_body = _request(base, f"/api/messages/{event['payload']['message_id']}", poll_token)["message"].get("body", "")
                    if re.search(r"(?<!\w)@(all|channel)\b", message_body, re.IGNORECASE):
                        targets = list(bots.values())
                    for target in targets:
                        if author == target["bot_user_id"]:
                            continue
                        text, history = _context_packet(base, target["token"], event["channel_id"], event["payload"]["message_id"])
                        agent, llm = get_agent(target["agent"]), None
                        if agent:
                            llm = load_llm_config(agent["path"])
                        if not agent or not llm:
                            _reply(base, target["token"], event["channel_id"], "I cannot start: this mapped Pipal agent is unavailable.")
                            continue
                        prompt = f"""You are @{target['handle']}, responding in a ClickClack channel.

Recent channel context:
{history}

The message directed to you is:
{text}

Reply directly and concisely. Do not claim to have read context not included above."""
                        turn_id = event["payload"]["message_id"]
                        _typing(base, target["token"], workspace, event["channel_id"], turn_id, True)
                        try:
                            answer = run_agent_print(agent["path"], llm, prompt).strip()
                            _reply(base, target["token"], event["channel_id"], answer or "I could not produce a response.")
                        finally:
                            _typing(base, target["token"], workspace, event["channel_id"], turn_id, False)
        except Exception as exc:
            print(f"ClickClack connection closed ({exc}); retrying in 2s.")
            time.sleep(2)
