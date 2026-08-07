from __future__ import annotations

import json
import os
from pathlib import Path

from .conversation_runtime import (
    fork_session_to_cwd as _fork_session_to_cwd,
    new_session_file as _new_session_file,
    session_cwd as _session_cwd,
    session_for_cwd as _session_for_cwd,
)
from .llm_config import load_llm_config
from .registry import get_agent
from .runner import _find_native_pi, load_persona
from .team_storage import latest_jsonl, team_topic_dir


TEAM_EXTENSION = Path(__file__).resolve().parent / "extensions" / "team_chat.ts"


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _acquire_room_lock(lock_file: Path) -> None:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                owner_pid = int(lock_file.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                owner_pid = -1
            if _pid_is_alive(owner_pid):
                raise ValueError(
                    f"Team topic is already open by process {owner_pid}: {lock_file.parent.name}"
                )
            lock_file.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
        return
    raise ValueError(f"Could not acquire team topic lock: {lock_file}")


def _release_room_lock(lock_file: Path) -> None:
    try:
        owner_pid = int(lock_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if owner_pid == os.getpid():
        lock_file.unlink(missing_ok=True)


def _member_context(
    team: dict,
    member: dict,
    topic_name: str,
    agent_path: Path,
    transcript_file: Path,
    working_dir: Path,
) -> str:
    roster = "\n".join(
        f"- @{item['agent']}: {item.get('role', 'Member')}"
        for item in team.get("members", [])
    )
    return f"""# Pipal team member context

You are @{member['agent']}, the **{member.get('role', 'Member')}** in the Pipal team **{team['name']}**.
The human owner is **{team.get('owner', 'the user')}**. The team manager is **@{team['manager']}**.
Current shared topic: **{topic_name}**.
Shared working directory: `{working_dir.resolve()}`. Run relative file and shell operations there unless explicitly asked to use another location.

Team roster:
{roster}

Shared topic transcript: `{transcript_file.resolve()}`
- This append-only JSONL file is the team's canonical ordered chat history, separate from your private Pi session.
- Each line records an owner/agent message or relevant tool activity with attribution and timestamp.
- Do not read it routinely. Use the `read` tool when a request references earlier messages, asks you to confirm another agent, is ambiguous without history, or otherwise requires shared context.

When another team member delegates work:
- Answer from your assigned role, with an independent point of view.
- Be concise, concrete, and honest about uncertainty.
- Challenge assumptions when your role requires it.
- You may address another member with @name when their input would help.
- Do not pretend that you performed work or consulted agents when you did not.

Your persistent agent home is {agent_path.resolve()}.
"""


def _manager_context(
    team: dict,
    topic_name: str,
    agent_path: Path,
    transcript_file: Path,
    working_dir: Path,
) -> str:
    roster = "\n".join(
        f"- @{item['agent']}: {item.get('role', 'Member')}"
        for item in team.get("members", [])
    )
    other_members = [
        item for item in team.get("members", []) if item.get("agent") != team.get("manager")
    ]
    delegation_rule = (
        "For substantive, ambiguous, or high-impact requests, consult relevant members by "
        "@mentioning them in your response. Pipal deterministically routes those mentions and returns their replies to you."
        if other_members
        else "The team currently has no members besides you; answer directly."
    )
    return f"""# Pipal team manager context

You are @{team['manager']}, manager of the human-owned Pipal team **{team['name']}**.
The owner is **{team.get('owner', 'the user')}**. Current shared topic: **{topic_name}**.
Shared working directory: `{working_dir.resolve()}`. Run relative file and shell operations there unless explicitly asked to use another location.

Team roster:
{roster}

Shared topic transcript: `{transcript_file.resolve()}`
This append-only JSONL file is the team's canonical ordered chat history, separate from every agent's private Pi session. Agents may inspect it with the `read` tool when prior shared context is needed; do not load it routinely.

{delegation_rule}

Operating rules:
- Use each member according to their role; do not ask everyone by default when one specialist is enough.
- Never fabricate another member's opinion. Explicitly @mention them to consult them.
- When their replies are returned to you, synthesize the useful result and clearly surface meaningful disagreement.
- Keep normal answers concise; let the visible team discussion provide supporting detail.
- Stop mentioning agents when the question is answered. Avoid loops and respect the configured turn budget.

Your persistent agent home is {agent_path.resolve()}.
"""


def build_team_runtime(team: dict, topic_name: str, *, new_session: bool = False) -> tuple[dict, Path]:
    current_topic = team_topic_dir(team["name"], topic_name)
    prompt_dir = current_topic / "runtime-prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = current_topic / "transcript.jsonl"
    working_dir = Path.cwd().resolve()

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
        member_session = _session_for_cwd(member_session, member_sessions, working_dir)

        prompt = load_persona(agent["path"])
        team_context = _member_context(
            team,
            member,
            topic_name,
            agent_path,
            transcript_file,
            working_dir,
        )
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

    manager_persona = load_persona(manager["agent_path"])
    manager_context = _manager_context(
        team,
        topic_name,
        Path(manager["agent_path"]),
        transcript_file,
        working_dir,
    )
    manager_prompt = f"{manager_context}\n\n---\n\n{manager_persona}" if manager_persona else manager_context
    manager_prompt_file = prompt_dir / f"{manager['agent']}-manager.md"
    manager_prompt_file.write_text(manager_prompt, encoding="utf-8")
    manager["prompt_file"] = str(manager_prompt_file.resolve())

    runtime = {
        "schema_version": 1,
        "team": team["name"],
        "owner": team.get("owner", "Mo"),
        "manager": team["manager"],
        "topic": topic_name,
        "topic_dir": str(current_topic.resolve()),
        "transcript_file": str(transcript_file.resolve()),
        "working_dir": str(working_dir),
        "native_pi": _find_native_pi(),
        "max_rounds": int(team.get("max_rounds", 4)),
        "agent_timeout_seconds": int(team.get("agent_timeout_seconds", 300)),
        "members": runtime_members,
    }
    runtime_path = current_topic / "runtime.json"
    runtime_path.write_text(json.dumps(runtime, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return runtime, Path(manager["session_file"])


def run_team_chat(team: dict, topic_name: str, *, new_session: bool = False) -> None:
    if not TEAM_EXTENSION.exists():
        raise FileNotFoundError(f"Missing team TUI extension: {TEAM_EXTENSION}")

    lock_file = team_topic_dir(team["name"], topic_name) / ".room.lock"
    _acquire_room_lock(lock_file)
    try:
        runtime, _session_file = build_team_runtime(team, topic_name, new_session=new_session)

        # Pi provides the familiar terminal shell, but Pipal owns the room. The host
        # has no model turn or persisted session; every participant runs through its
        # independent native Pi session and the shared transcript is canonical.
        cmd = [
            runtime["native_pi"],
            "--no-session",
            "--no-tools",
            "--extension",
            str(TEAM_EXTENSION),
        ]

        env = os.environ.copy()
        env.pop("PIPAL_AGENT_DIR", None)
        env.update(
            {
                "PIPAL_TEAM_RUNTIME": str((Path(runtime["topic_dir"]) / "runtime.json").resolve()),
                "PIPAL_TEAM": runtime["team"],
                "PIPAL_TOPIC": topic_name,
                "PIPAL_TEAM_LOCK_FILE": str(lock_file.resolve()),
                "PIPAL_DISABLE_AUTOGREET": "1",
            }
        )
        os.execve(runtime["native_pi"], cmd, env)
    except BaseException:
        _release_room_lock(lock_file)
        raise
