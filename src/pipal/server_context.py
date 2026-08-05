from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .runner import load_persona as _load_persona, _read_agent_type as read_agent_type
from .topic_storage import topic_dir, topic_sessions_dir


def load_persona(agent_dir: Path) -> str:
    return _load_persona(str(agent_dir))


DEFAULT_TOPIC_TITLE = "New topic"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _topic_meta_path(current_topic_dir: Path) -> Path:
    return current_topic_dir / "topic.json"


def _read_topic_meta(current_topic_dir: Path) -> dict:
    meta_path = _topic_meta_path(current_topic_dir)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_topic_meta(current_topic_dir: Path, meta: dict) -> None:
    current_topic_dir.mkdir(parents=True, exist_ok=True)
    _topic_meta_path(current_topic_dir).write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _latest_session_mtime(current_topic_dir: Path) -> str:
    files = list((current_topic_dir / "sessions").glob("*.jsonl"))
    if not files:
        return _mtime_iso(current_topic_dir)
    latest = max(files, key=lambda p: p.stat().st_mtime)
    return _mtime_iso(latest)


def ensure_topic_meta(current_topic_dir: Path) -> dict:
    meta = _read_topic_meta(current_topic_dir)
    created_at = meta.get("created_at")
    updated_at = meta.get("updated_at")
    title = meta.get("title")

    if not created_at:
        created_at = _mtime_iso(current_topic_dir) if current_topic_dir.exists() else _now_iso()
    if not updated_at:
        updated_at = _latest_session_mtime(current_topic_dir) if current_topic_dir.exists() else _now_iso()
    if not title:
        title = DEFAULT_TOPIC_TITLE

    meta = {"created_at": created_at, "updated_at": updated_at, "title": title}
    _write_topic_meta(current_topic_dir, meta)
    return meta


def update_topic_meta(
    current_topic_dir: Path,
    *,
    updated_at: str | None = None,
    title: str | None = None,
) -> dict:
    meta = ensure_topic_meta(current_topic_dir)
    if title is not None:
        meta["title"] = title
    meta["updated_at"] = updated_at or _now_iso()
    _write_topic_meta(current_topic_dir, meta)
    return meta


def update_topic_title_from_prompt(current_topic_dir: Path, prompt: str) -> dict:
    prompt = " ".join(prompt.split()).strip()
    if not prompt:
        return ensure_topic_meta(current_topic_dir)
    meta = ensure_topic_meta(current_topic_dir)
    if meta.get("title") and meta.get("title") != DEFAULT_TOPIC_TITLE:
        return meta
    return update_topic_meta(current_topic_dir, title=prompt[:60])


def new_session_file(agent_dir: Path, topic_name: str) -> Path:
    sessions_dir = topic_sessions_dir(agent_dir, topic_name)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_file = sessions_dir / f"{ts}_{uuid4().hex[:8]}.jsonl"
    ensure_topic_meta(topic_dir(agent_dir, topic_name))
    return session_file
