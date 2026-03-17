from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from .runner import PERSONA_FILES


def load_persona(agent_dir: Path) -> str:
    parts: list[str] = []
    for name in PERSONA_FILES:
        path = agent_dir / name
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
    return "\n\n---\n\n".join(parts)


def load_summary(agent_dir: Path, session_name: str = "main") -> str:
    summary_path = agent_dir / "sessions" / session_name / "summary.md"
    if summary_path.exists():
        try:
            return summary_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def new_session_file(agent_dir: Path, session_name: str) -> Path:
    sessions_dir = agent_dir / "sessions" / session_name
    sessions_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return sessions_dir / f"{ts}.jsonl"


def read_agent_type(agent_dir: Path) -> str | None:
    type_path = agent_dir / ".pipal_type"
    if not type_path.exists():
        return None
    try:
        return type_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
