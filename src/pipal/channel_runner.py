from __future__ import annotations

import json
import os
from pathlib import Path

from .channel_storage import channel_topic_dir
from .conversation_runtime import session_for_cwd
from .llm_config import load_llm_config
from .registry import get_agent
from .runner import _find_native_pi, load_persona
from .team_runner import TEAM_EXTENSION, _acquire_room_lock, _release_room_lock
from .team_storage import latest_jsonl


def build_channel_runtime(channel: dict, topic_name: str, *, new_session: bool = False) -> dict:
    current_topic = channel_topic_dir(channel["name"], topic_name)
    prompt_dir = current_topic / "runtime-prompts"; prompt_dir.mkdir(exist_ok=True)
    transcript = current_topic / "transcript.jsonl"
    cwd = Path.cwd().resolve()
    members = []
    roster = "\n".join(f"- @{m['agent']}: {m.get('role', 'Member')}" for m in channel["members"])
    for member in channel["members"]:
        agent = get_agent(member["agent"])
        if not agent: raise ValueError(f"Unknown channel agent: {member['agent']}")
        llm = load_llm_config(agent["path"])
        if not llm: raise ValueError(f"Agent {member['agent']} has no llm.json")
        sessions = current_topic / "members" / member["agent"] / "sessions"
        session = None if new_session else latest_jsonl(sessions)
        session = session_for_cwd(session, sessions, cwd)
        context = f'''# Pipal channel member context

You are @{member['agent']}, a participant in the Pipal channel **#{channel['name']}**.
The human owner is **{channel.get('owner', 'the user')}**. Shared working directory: `{cwd}`.

Channel members:
{roster}

The canonical visible conversation is `{transcript}`. It is an append-only event stream, while your Pi session is private working context. Read the transcript only when needed for relevant earlier context.

Reply only to messages that explicitly @mention you. You may @mention another channel member when their input is needed. Be concise, honest about uncertainty, and do not claim work or consultation you did not perform.
'''
        persona = load_persona(agent["path"])
        prompt = f"{context}\n\n---\n\n{persona}" if persona else context
        prompt_file = prompt_dir / f"{member['agent']}.md"; prompt_file.write_text(prompt, encoding="utf-8")
        members.append({**member, "agent_path": str(Path(agent["path"]).resolve()), "provider": llm.get("provider"), "model": llm.get("model"), "prompt_file": str(prompt_file.resolve()), "session_file": str(session.resolve())})
    runtime = {"schema_version": 1, "kind": "channel", "channel": channel["name"], "team": channel["name"], "owner": channel.get("owner", "Mo"), "topic": topic_name, "topic_dir": str(current_topic.resolve()), "transcript_file": str(transcript.resolve()), "working_dir": str(cwd), "native_pi": _find_native_pi(), "max_rounds": int(channel.get("max_rounds", 4)), "agent_timeout_seconds": int(channel.get("agent_timeout_seconds", 300)), "members": members}
    (current_topic / "runtime.json").write_text(json.dumps(runtime, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return runtime


def run_channel_chat(channel: dict, topic_name: str, *, new_session: bool = False) -> None:
    lock = channel_topic_dir(channel["name"], topic_name) / ".room.lock"
    _acquire_room_lock(lock)
    try:
        runtime = build_channel_runtime(channel, topic_name, new_session=new_session)
        env = os.environ.copy(); env.pop("PIPAL_AGENT_DIR", None)
        env.update({"PIPAL_TEAM_RUNTIME": str((Path(runtime["topic_dir"]) / "runtime.json").resolve()), "PIPAL_TEAM": runtime["team"], "PIPAL_TOPIC": topic_name, "PIPAL_TEAM_LOCK_FILE": str(lock.resolve()), "PIPAL_DISABLE_AUTOGREET": "1"})
        os.execve(runtime["native_pi"], [runtime["native_pi"], "--no-session", "--no-tools", "--extension", str(TEAM_EXTENSION)], env)
    except BaseException:
        _release_room_lock(lock); raise
