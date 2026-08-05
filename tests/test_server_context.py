import json

from pipal.server_context import (
    DEFAULT_TOPIC_TITLE,
    ensure_topic_meta,
    update_topic_meta,
    update_topic_title_from_prompt,
)


def test_ensure_topic_meta_creates_directory_and_file(tmp_path):
    current_topic_dir = tmp_path / "topics" / "main"
    meta = ensure_topic_meta(current_topic_dir)

    assert current_topic_dir.exists()
    assert (current_topic_dir / "topic.json").exists()
    assert meta["title"] == DEFAULT_TOPIC_TITLE
    assert "created_at" in meta
    assert "updated_at" in meta


def test_update_topic_title_from_prompt_only_sets_default_title(tmp_path):
    current_topic_dir = tmp_path / "topics" / "main"
    ensure_topic_meta(current_topic_dir)

    update_topic_title_from_prompt(current_topic_dir, "   Hello   world   from user   ")
    first = json.loads((current_topic_dir / "topic.json").read_text())
    assert first["title"] == "Hello world from user"

    update_topic_title_from_prompt(current_topic_dir, "Another prompt should not override")
    second = json.loads((current_topic_dir / "topic.json").read_text())
    assert second["title"] == "Hello world from user"


def test_update_topic_meta_explicit_title(tmp_path):
    current_topic_dir = tmp_path / "topics" / "dev"
    ensure_topic_meta(current_topic_dir)
    meta = update_topic_meta(current_topic_dir, title="Deep work")
    assert meta["title"] == "Deep work"
