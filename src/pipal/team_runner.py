from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .llm_config import load_llm_config
from .registry import get_agent
from .runner import _find_native_pi, load_persona
from .team_storage import latest_jsonl, team_topic_dir


TEAM_EXTENSION = Path(__file__).resolve().parent / "extensions" / "team_chat.ts"


def _new_session_file(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return directory / f"{timestamp}_{uuid4().hex[:8]}.jsonl"


def _member_context(team: dict, member: dict, topic_name: str, agent_path: Path) -> str:
    roster = "\n".join(
        f"- @{item['agent']}: {item.get('role', 'Member')}"
        for item in team.get("members", [])
    )
    return f"""# Pipal team member context

You are @{member['agent']}, the **{member.get('role', 'Member')}** in the Pipal team **{team['name']}**.
The human owner is **{team.get('owner', 'the user')}**. The team manager is **@{team['manager']}**.
Current shared topic: **{topic_name}**.

Team roster:
{roster}

When another team member delegates work:
- Answer from your assigned role, with an independent point of view.
- Be concise, concrete, and honest about uncertainty.
- Challenge assumptions when your role requires it.
- You may address another member with @name when their input would help.
- Do not pretend that you performed work or consulted agents when you did not.

Your persistent agent home is {agent_path.resolve()}.
"""


def _manager_context(team: dict, topic_name: str, agent_path: Path) -> str:
    roster = "\n".join(
        f"- @{item['agent']}: {item.get('role', 'Member')}"
        for item in team.get("members", [])
    )
    other_members = [
        item for item in team.get("members", []) if item.get("agent") != team.get("manager")
    ]
    delegation_rule = (
        "For substantive, ambiguous, or high-impact requests, consult relevant members with "
        "team_delegate before answering. You can call multiple members in parallel."
        if other_members
        else "The team currently has no members besides you; answer directly."
    )
    return f"""# Pipal team manager context

You are @{team['manager']}, manager of the human-owned Pipal team **{team['name']}**.
The owner is **{team.get('owner', 'the user')}**. Current shared topic: **{topic_name}**.

Team roster:
{roster}

{delegation_rule}

Operating rules:
- Use each member according to their role; do not ask everyone by default when one specialist is enough.
- Never fabricate another member's opinion. Use team_delegate to actually consult them.
- After delegation, synthesize the useful result and clearly surface meaningful disagreement.
- A direct @member message from the owner must be delegated to that member.
- Keep normal answers concise; let the visible team discussion provide supporting detail.
- Stop delegating when the question is answered. Avoid agent loops and respect the configured turn budget.

Your persistent agent home is {agent_path.resolve()}.
"""


def build_team_runtime(team: dict, topic_name: str, *, new_session: bool = False) -> tuple[dict, Path]:
    current_topic = team_topic_dir(team["name"], topic_name)
    prompt_dir = current_topic / "runtime-prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    runtime_members: list[dict] = []
    for member in team.get("members", []):
        agent = get_agent(member["agent"])
        if not agent:
            raise ValueError(f"Unknown team agent: {member['agent']}")
        llm = load_llm_config(agent["path"])
        if not llm:
            raise ValueError(f"Agent {member['agent']} has no llm.json")

        agent_path = Path(agent["path"])
        member_sessions = current_topic / "members" / member["agent"] / "sessions"
        member_session = None if new_session else latest_jsonl(member_sessions)
        member_session = member_session or _new_session_file(member_sessions)

        prompt = load_persona(agent["path"])
        team_context = _member_context(team, member, topic_name, agent_path)
        prompt_text = f"{team_context}\n\n---\n\n{prompt}" if prompt else team_context
        prompt_file = prompt_dir / f"{member['agent']}.md"
        prompt_file.write_text(prompt_text, encoding="utf-8")

        runtime_members.append(
            {
                **member,
                "agent_path": str(agent_path.resolve()),
                "provider": llm.get("provider"),
                "model": llm.get("model"),
                "prompt_file": str(prompt_file.resolve()),
                "session_file": str(member_session.resolve()),
            }
        )

    manager = next(
        (member for member in runtime_members if member["agent"] == team["manager"]),
        None,
    )
    if not manager:
        raise ValueError(f"Manager {team['manager']} is not a team member")

    main_sessions = current_topic / "sessions"
    main_session = None if new_session else latest_jsonl(main_sessions)
    main_session = main_session or _new_session_file(main_sessions)

    manager_persona = load_persona(manager["agent_path"])
    manager_context = _manager_context(team, topic_name, Path(manager["agent_path"]))
    manager_prompt = f"{manager_context}\n\n---\n\n{manager_persona}" if manager_persona else manager_context
    manager_prompt_file = prompt_dir / f"{manager['agent']}-manager.md"
    manager_prompt_file.write_text(manager_prompt, encoding="utf-8")

    runtime = {
        "schema_version": 1,
        "team": team["name"],
        "owner": team.get("owner", "Mo"),
        "manager": team["manager"],
        "topic": topic_name,
        "topic_dir": str(current_topic.resolve()),
        "native_pi": _find_native_pi(),
        "max_rounds": int(team.get("max_rounds", 4)),
        "members": runtime_members,
    }
    runtime_path = current_topic / "runtime.json"
    runtime_path.write_text(json.dumps(runtime, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return runtime, main_session


def run_team_chat(team: dict, topic_name: str, *, new_session: bool = False) -> None:
    if not TEAM_EXTENSION.exists():
        raise FileNotFoundError(f"Missing team TUI extension: {TEAM_EXTENSION}")

    runtime, session_file = build_team_runtime(team, topic_name, new_session=new_session)
    manager = next(member for member in runtime["members"] if member["agent"] == runtime["manager"])
    manager_prompt = Path(runtime["topic_dir"]) / "runtime-prompts" / f"{runtime['manager']}-manager.md"

    cmd = [
        runtime["native_pi"],
        "--session",
        str(session_file.resolve()),
        "--extension",
        str(TEAM_EXTENSION),
        "--append-system-prompt",
        str(manager_prompt.resolve()),
    ]
    if manager.get("provider"):
        cmd += ["--provider", manager["provider"]]
    if manager.get("model"):
        cmd += ["--model", manager["model"]]

    env = os.environ.copy()
    env.update(
        {
            "PIPAL_TEAM_RUNTIME": str((Path(runtime["topic_dir"]) / "runtime.json").resolve()),
            "PIPAL_TEAM": runtime["team"],
            "PIPAL_TOPIC": topic_name,
            "PIPAL_AGENT_DIR": manager["agent_path"],
            "PIPAL_DISABLE_AUTOGREET": "1",
        }
    )
    os.execve(runtime["native_pi"], cmd, env)
