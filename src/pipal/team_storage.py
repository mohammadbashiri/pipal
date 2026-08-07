from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .registry import pipal_dir
from .topic_storage import validate_topic_name


def validate_team_name(team_name: str) -> str:
    name = team_name.strip()
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ValueError(f"Invalid team name: {team_name!r}")
    return name


def teams_root() -> Path:
    root = pipal_dir() / "teams"
    root.mkdir(parents=True, exist_ok=True)
    return root


def team_dir(team_name: str) -> Path:
    return teams_root() / validate_team_name(team_name)


def team_config_path(team_name: str) -> Path:
    return team_dir(team_name) / "team.json"


def list_teams() -> list[dict]:
    teams: list[dict] = []
    for path in sorted(teams_root().iterdir()):
        if not path.is_dir() or not (path / "team.json").is_file():
            continue
        try:
            teams.append(json.loads((path / "team.json").read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return teams


def load_team(team_name: str) -> dict | None:
    path = team_config_path(team_name)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def save_team(team: dict) -> Path:
    name = validate_team_name(str(team.get("name", "")))
    path = team_config_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(team, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def create_team(
    name: str,
    manager: str,
    members: Iterable[tuple[str, str]],
    *,
    owner: str = "Mo",
    max_rounds: int = 4,
) -> dict:
    name = validate_team_name(name)
    if load_team(name):
        raise ValueError(f"Team already exists: {name}")

    ordered: list[dict[str, str]] = []
    seen: set[str] = set()
    for agent, role in [(manager, "Manager"), *members]:
        agent = agent.strip()
        role = role.strip() or "Member"
        if not agent or agent in seen:
            continue
        ordered.append({"agent": agent, "role": role})
        seen.add(agent)

    if manager not in seen:
        raise ValueError("Manager must be a team member")

    now = datetime.now(timezone.utc).isoformat()
    team = {
        "schema_version": 1,
        "name": name,
        "owner": owner,
        "manager": manager,
        "members": ordered,
        "max_rounds": max(1, max_rounds),
        "created_at": now,
        "updated_at": now,
    }
    save_team(team)
    (team_dir(name) / "topics").mkdir(parents=True, exist_ok=True)
    return team


def remove_team(team_name: str) -> bool:
    path = team_dir(team_name)
    if not path.exists():
        return False
    shutil.rmtree(path)
    return True


def team_topic_dir(team_name: str, topic_name: str = "main") -> Path:
    path = team_dir(team_name) / "topics" / validate_topic_name(topic_name)
    path.mkdir(parents=True, exist_ok=True)
    (path / "sessions").mkdir(parents=True, exist_ok=True)
    (path / "members").mkdir(parents=True, exist_ok=True)
    (path / "transcript.jsonl").touch(exist_ok=True)
    return path


def latest_jsonl(directory: Path) -> Path | None:
    files = list(directory.glob("*.jsonl"))
    return max(files, key=lambda item: (item.stat().st_mtime, item.name)) if files else None
