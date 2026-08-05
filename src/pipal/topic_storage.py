from __future__ import annotations

import shutil
from pathlib import Path


def topics_root(agent_path: str | Path) -> Path:
    """Return the canonical topic root, migrating legacy Pipal sessions first."""
    agent = Path(agent_path)
    migrate_legacy_sessions(agent)
    root = agent / "topics"
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_topic_name(topic_name: str) -> str:
    name = topic_name.strip()
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ValueError(f"Invalid topic name: {topic_name!r}")
    return name


def topic_dir(agent_path: str | Path, topic_name: str = "main") -> Path:
    root = topics_root(agent_path)
    path = root / validate_topic_name(topic_name)
    path.mkdir(parents=True, exist_ok=True)
    _normalize_topic(path)
    return path


def topic_sessions_dir(agent_path: str | Path, topic_name: str = "main") -> Path:
    path = topic_dir(agent_path, topic_name) / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def migrate_legacy_sessions(agent: Path) -> bool:
    """Migrate sessions/<topic>/*.jsonl to topics/<topic>/sessions/*.jsonl."""
    legacy_root = agent / "sessions"
    canonical_root = agent / "topics"
    changed = False

    if legacy_root.exists():
        canonical_root.mkdir(parents=True, exist_ok=True)
        for source in sorted(legacy_root.iterdir()):
            if not source.is_dir():
                continue
            target = canonical_root / source.name
            if not target.exists():
                shutil.move(str(source), str(target))
                changed = True
            else:
                for item in source.iterdir():
                    destination = target / item.name
                    if not destination.exists():
                        shutil.move(str(item), str(destination))
                        changed = True
                try:
                    source.rmdir()
                except OSError:
                    pass
        try:
            legacy_root.rmdir()
        except OSError:
            pass

    if canonical_root.exists():
        for path in canonical_root.iterdir():
            if path.is_dir() and _normalize_topic(path):
                changed = True

    return changed


def _normalize_topic(path: Path) -> bool:
    """Normalize a topic directory created by the legacy flat layout."""
    changed = False
    sessions = path / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)

    for session_file in path.glob("*.jsonl"):
        destination = sessions / session_file.name
        if not destination.exists():
            session_file.replace(destination)
            changed = True

    old_meta = path / "session.json"
    new_meta = path / "topic.json"
    if old_meta.exists() and not new_meta.exists():
        old_meta.replace(new_meta)
        changed = True

    return changed
