from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .registry import pipal_dir
from .topic_storage import validate_topic_name


def validate_channel_name(name: str) -> str:
    value = name.strip()
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError(f"Invalid channel name: {name!r}")
    return value


def channels_root() -> Path:
    root = pipal_dir() / "channels"
    root.mkdir(parents=True, exist_ok=True)
    return root


def channel_dir(name: str) -> Path:
    return channels_root() / validate_channel_name(name)


def channel_config_path(name: str) -> Path:
    return channel_dir(name) / "channel.json"


def load_channel(name: str) -> dict | None:
    path = channel_config_path(name)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def list_channels() -> list[dict]:
    result: list[dict] = []
    for path in sorted(channels_root().iterdir()):
        if path.is_dir() and (path / "channel.json").is_file():
            channel = load_channel(path.name)
            if channel:
                result.append(channel)
    return result


def create_channel(name: str, members: Iterable[tuple[str, str]], *, owner: str = "Mo", max_rounds: int = 4) -> dict:
    name = validate_channel_name(name)
    if load_channel(name):
        raise ValueError(f"Channel already exists: {name}")
    seen: set[str] = set()
    roster = []
    for agent, role in members:
        agent, role = agent.strip(), role.strip() or "Member"
        if agent and agent not in seen:
            roster.append({"agent": agent, "role": role})
            seen.add(agent)
    if not roster:
        raise ValueError("A channel needs at least one agent member")
    now = datetime.now(timezone.utc).isoformat()
    channel = {"schema_version": 1, "name": name, "owner": owner, "members": roster, "max_rounds": max(1, max_rounds), "created_at": now, "updated_at": now}
    path = channel_config_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(channel, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (channel_dir(name) / "topics").mkdir(exist_ok=True)
    return channel


def remove_channel(name: str) -> bool:
    path = channel_dir(name)
    if not path.exists():
        return False
    shutil.rmtree(path)
    return True


def channel_topic_dir(name: str, topic: str = "main") -> Path:
    path = channel_dir(name) / "topics" / validate_topic_name(topic)
    path.mkdir(parents=True, exist_ok=True)
    (path / "members").mkdir(exist_ok=True)
    (path / "transcript.jsonl").touch(exist_ok=True)
    return path
