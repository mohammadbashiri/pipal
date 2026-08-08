from __future__ import annotations

import json
import sys
from pathlib import Path

from .conversation_runtime import session_for_cwd
from .llm_config import load_llm_config
from .registry import list_agents
from .runner import _find_native_pi, load_persona
from .team_storage import latest_jsonl, list_teams


DELEGATION_EXTENSION = Path(__file__).resolve().parent / "extensions" / "delegation.ts"


def _delegate_context(
    *,
    primary_name: str,
    delegate_name: str,
    topic_name: str,
    working_dir: Path,
    transcript_file: Path,
    agent_path: Path,
) -> str:
    return f"""# Pipal delegated-agent context

You are **@agent:{delegate_name}**, a persistent Pipal agent helping **@agent:{primary_name}** complete work for the human owner.
Current primary-agent topic: **{topic_name}**.
Shared working directory: `{working_dir}`. Run relative file and shell operations there unless explicitly told otherwise.
Delegation transcript: `{transcript_file}`.

The transcript is an append-only JSONL record of messages in this persistent delegation thread. Read it lazily when the current message references earlier work or you need prior context.

Working rules:
- Perform the requested work rather than merely suggesting how it could be done.
- Return concrete results, artifacts, evidence, and blockers.
- Be honest about uncertainty and verification.
- Do not claim completion when acceptance criteria remain unmet.
- Ask the primary agent a focused question when genuinely blocked.
- Return only your response body; Pipal adds attribution.

Your persistent agent home is `{agent_path}`.
"""


def build_delegation_runtime(
    primary_name: str,
    primary_path: str,
    topic_name: str,
    *,
    working_dir: Path | None = None,
) -> tuple[dict, Path]:
    primary_home = Path(primary_path).resolve()
    cwd = (working_dir or Path.cwd()).resolve()
    root = primary_home / "topics" / topic_name / "delegations"
    prompt_dir = root / "runtime-prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    delegates: list[dict] = []
    for registered_name, registered_path in list_agents().items():
        name = str(registered_name).strip()
        if not name or name == primary_name:
            continue
        agent_path = Path(registered_path).resolve()
        llm = load_llm_config(str(agent_path))
        if not llm:
            continue

        delegate_dir = root / name
        sessions_dir = delegate_dir / "sessions"
        transcript_file = delegate_dir / "transcript.jsonl"
        transcript_file.parent.mkdir(parents=True, exist_ok=True)
        transcript_file.touch(exist_ok=True)
        session = session_for_cwd(latest_jsonl(sessions_dir), sessions_dir, cwd)

        context = _delegate_context(
            primary_name=primary_name,
            delegate_name=name,
            topic_name=topic_name,
            working_dir=cwd,
            transcript_file=transcript_file.resolve(),
            agent_path=agent_path,
        )
        persona = load_persona(str(agent_path))
        prompt_text = f"{context}\n\n---\n\n{persona}" if persona else context
        prompt_file = prompt_dir / f"{name}.md"
        prompt_file.write_text(prompt_text, encoding="utf-8")

        delegates.append(
            {
                "agent": name,
                "role": "Pipal agent",
                "agent_path": str(agent_path),
                "provider": llm.get("provider"),
                "model": llm.get("model"),
                "prompt_file": str(prompt_file.resolve()),
                "session_file": str(session.resolve()),
                "transcript_file": str(transcript_file.resolve()),
            }
        )

    available = {item["agent"] for item in delegates}
    teams: list[dict] = []
    for team in list_teams():
        members = [
            member for member in team.get("members", [])
            if member.get("agent") == primary_name or member.get("agent") in available
        ]
        if members:
            teams.append({
                "name": team.get("name"),
                "manager": team.get("manager"),
                "members": members,
            })

    runtime = {
        "schema_version": 2,
        "primary": primary_name,
        "primary_path": str(primary_home),
        "topic": topic_name,
        "working_dir": str(cwd),
        "native_pi": _find_native_pi(),
        "agent_timeout_seconds": 300,
        "max_turns": 8,
        "background_root": str((root / "jobs").resolve()),
        "worker_python": sys.executable,
        "delegates": delegates,
        "teams": teams,
    }
    runtime_file = root / "runtime.json"
    runtime_file.write_text(json.dumps(runtime, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return runtime, runtime_file
