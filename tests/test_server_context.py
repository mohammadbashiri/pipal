import json
from pathlib import Path

from pipal.server_context import (
    DEFAULT_SESSION_TITLE,
    ensure_session_meta,
    update_session_meta,
    update_session_title_from_prompt,
)


def test_ensure_session_meta_creates_directory_and_file(tmp_path):
    session_dir = tmp_path / "sessions" / "main"
    meta = ensure_session_meta(session_dir)

    assert session_dir.exists()
    assert (session_dir / "session.json").exists()
    assert meta["title"] == DEFAULT_SESSION_TITLE
    assert "created_at" in meta
    assert "updated_at" in meta


def test_update_session_title_from_prompt_only_sets_default_title(tmp_path):
    session_dir = tmp_path / "sessions" / "main"
    ensure_session_meta(session_dir)

    update_session_title_from_prompt(session_dir, "   Hello   world   from user   ")
    first = json.loads((session_dir / "session.json").read_text())
    assert first["title"] == "Hello world from user"

    update_session_title_from_prompt(session_dir, "Another prompt should not override")
    second = json.loads((session_dir / "session.json").read_text())
    assert second["title"] == "Hello world from user"


def test_update_session_meta_explicit_title(tmp_path):
    session_dir = tmp_path / "sessions" / "dev"
    ensure_session_meta(session_dir)
    meta = update_session_meta(session_dir, title="Deep work")
    assert meta["title"] == "Deep work"
