from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def new_session_file(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return directory / f"{timestamp}_{uuid4().hex[:8]}.jsonl"


def session_cwd(session_file: Path) -> Path | None:
    try:
        first_line = session_file.open(encoding="utf-8").readline()
        header = json.loads(first_line)
        cwd = header.get("cwd") if header.get("type") == "session" else None
        return Path(cwd).resolve() if isinstance(cwd, str) and cwd else None
    except (OSError, json.JSONDecodeError):
        return None


def fork_session_to_cwd(session_file: Path, target_cwd: Path) -> Path:
    """Fork a native Pi session while preserving its complete entry history."""
    lines = session_file.read_text(encoding="utf-8").splitlines()
    if not lines:
        return session_file
    target = new_session_file(session_file.parent)
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    header = {
        "type": "session",
        "version": 3,
        "id": str(uuid4()),
        "timestamp": timestamp,
        "cwd": str(target_cwd.resolve()),
        "parentSession": str(session_file.resolve()),
    }
    target.write_text(
        "\n".join([json.dumps(header, ensure_ascii=False), *lines[1:]]) + "\n",
        encoding="utf-8",
    )
    return target


def session_for_cwd(session_file: Path | None, directory: Path, cwd: Path) -> Path:
    """Resume a native session or fork it when the communication cwd changed."""
    if session_file is None:
        return new_session_file(directory)
    existing_cwd = session_cwd(session_file)
    return (
        fork_session_to_cwd(session_file, cwd)
        if existing_cwd and existing_cwd != cwd
        else session_file
    )
