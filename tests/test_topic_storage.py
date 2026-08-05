from pathlib import Path

import pytest

from pipal.topic_storage import (
    migrate_legacy_sessions,
    topic_dir,
    topic_sessions_dir,
    validate_topic_name,
)


def test_topic_layout(tmp_path):
    current_topic = topic_dir(tmp_path, "work")
    sessions = topic_sessions_dir(tmp_path, "work")
    assert current_topic == tmp_path / "topics" / "work"
    assert sessions == current_topic / "sessions"
    assert sessions.is_dir()


def test_migrates_legacy_topic_layout(tmp_path):
    legacy = tmp_path / "sessions" / "main"
    legacy.mkdir(parents=True)
    (legacy / "summary.md").write_text("old summary", encoding="utf-8")
    (legacy / "session.json").write_text("{}", encoding="utf-8")
    (legacy / "20260101-000000_test.jsonl").write_text("{}\n", encoding="utf-8")

    assert migrate_legacy_sessions(tmp_path) is True

    current_topic = tmp_path / "topics" / "main"
    assert (current_topic / "summary.md").read_text(encoding="utf-8") == "old summary"
    assert (current_topic / "topic.json").exists()
    assert (current_topic / "sessions" / "20260101-000000_test.jsonl").exists()
    assert not (tmp_path / "sessions").exists()


def test_migration_is_idempotent(tmp_path):
    topic_sessions_dir(tmp_path, "main")
    assert migrate_legacy_sessions(tmp_path) is False


@pytest.mark.parametrize("name", ["", ".", "..", "../outside", "nested/topic"])
def test_rejects_invalid_topic_names(name):
    with pytest.raises(ValueError):
        validate_topic_name(name)
