from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .runner import load_persona as _load_persona, _read_agent_type as read_agent_type


def load_persona(agent_dir: Path) -> str:
    return _load_persona(str(agent_dir))


DEFAULT_SESSION_TITLE = "New chat"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _session_meta_path(session_dir: Path) -> Path:
    return session_dir / "session.json"


def _read_session_meta(session_dir: Path) -> dict:
    meta_path = _session_meta_path(session_dir)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_session_meta(session_dir: Path, meta: dict) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    meta_path = _session_meta_path(session_dir)
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _latest_session_mtime(session_dir: Path) -> str:
    files = list(session_dir.glob("*.jsonl"))
    if not files:
        return _mtime_iso(session_dir)
    latest = max(files, key=lambda p: p.stat().st_mtime)
    return _mtime_iso(latest)


def ensure_session_meta(session_dir: Path) -> dict:
    meta = _read_session_meta(session_dir)
    created_at = meta.get("created_at")
    updated_at = meta.get("updated_at")
    title = meta.get("title")

    if not created_at:
        created_at = _mtime_iso(session_dir) if session_dir.exists() else _now_iso()
    if not updated_at:
        updated_at = _latest_session_mtime(session_dir) if session_dir.exists() else _now_iso()
    if not title:
        title = DEFAULT_SESSION_TITLE

    meta = {"created_at": created_at, "updated_at": updated_at, "title": title}
    _write_session_meta(session_dir, meta)
    return meta


def update_session_meta(session_dir: Path, *, updated_at: str | None = None, title: str | None = None) -> dict:
    meta = ensure_session_meta(session_dir)
    if title is not None:
        meta["title"] = title
    meta["updated_at"] = updated_at or _now_iso()
    _write_session_meta(session_dir, meta)
    return meta


def update_session_title_from_prompt(session_dir: Path, prompt: str) -> dict:
    prompt = " ".join(prompt.split()).strip()
    if not prompt:
        return ensure_session_meta(session_dir)
    meta = ensure_session_meta(session_dir)
    if meta.get("title") and meta.get("title") != DEFAULT_SESSION_TITLE:
        return meta
    title = prompt[:60]
    return update_session_meta(session_dir, title=title)


def new_session_file(agent_dir: Path, session_name: str) -> Path:
    sessions_dir = agent_dir / "sessions" / session_name
    sessions_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_file = sessions_dir / f"{ts}.jsonl"
    update_session_meta(sessions_dir)
    return session_file


