import json

import pytest

from pipal.team_runner import _acquire_room_lock, _release_room_lock, _session_for_cwd
from pipal.team_storage import (
    create_team,
    list_teams,
    load_team,
    remove_team,
    team_topic_dir,
    validate_team_name,
)


def test_create_load_list_and_remove_team(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path))

    team = create_team(
        "life-board",
        "sasha",
        [("ada", "Researcher"), ("raven", "Risk Reviewer")],
        owner="Mo",
        max_rounds=3,
    )

    assert team["manager"] == "sasha"
    assert team["members"] == [
        {"agent": "sasha", "role": "Manager"},
        {"agent": "ada", "role": "Researcher"},
        {"agent": "raven", "role": "Risk Reviewer"},
    ]
    assert load_team("life-board") == team
    assert [item["name"] for item in list_teams()] == ["life-board"]

    topic = team_topic_dir("life-board", "insurance")
    assert (topic / "sessions").is_dir()
    assert (topic / "members").is_dir()
    assert (topic / "transcript.jsonl").is_file()

    assert remove_team("life-board") is True
    assert load_team("life-board") is None
    assert remove_team("life-board") is False


def test_team_topic_lock_rejects_live_owner_and_reclaims_stale_lock(tmp_path):
    lock_file = tmp_path / ".room.lock"
    _acquire_room_lock(lock_file)
    with pytest.raises(ValueError, match="already open"):
        _acquire_room_lock(lock_file)
    _release_room_lock(lock_file)
    assert not lock_file.exists()

    lock_file.write_text("999999999\n", encoding="utf-8")
    _acquire_room_lock(lock_file)
    assert int(lock_file.read_text(encoding="utf-8")) > 0
    _release_room_lock(lock_file)


def test_session_is_forked_when_team_working_directory_changes(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    original_cwd = tmp_path / "old"
    target_cwd = tmp_path / "project"
    original_cwd.mkdir()
    target_cwd.mkdir()
    original = sessions / "original.jsonl"
    original.write_text(
        json.dumps({
            "type": "session",
            "version": 3,
            "id": "old-id",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(original_cwd),
        })
        + "\n"
        + json.dumps({"type": "message", "id": "message-1", "message": {"role": "user"}})
        + "\n",
        encoding="utf-8",
    )

    forked = _session_for_cwd(original, sessions, target_cwd)

    assert forked != original
    lines = [json.loads(line) for line in forked.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["cwd"] == str(target_cwd)
    assert lines[0]["parentSession"] == str(original)
    assert lines[1]["id"] == "message-1"
    assert _session_for_cwd(forked, sessions, target_cwd) == forked


def test_create_team_deduplicates_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path))
    team = create_team("demo", "sasha", [("sasha", "Other"), ("ada", "Researcher")])
    assert team["members"] == [
        {"agent": "sasha", "role": "Manager"},
        {"agent": "ada", "role": "Researcher"},
    ]


def test_create_existing_team_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path))
    create_team("demo", "sasha", [])
    with pytest.raises(ValueError, match="already exists"):
        create_team("demo", "sasha", [])


@pytest.mark.parametrize("name", ["", ".", "..", "../outside", "nested/team"])
def test_validate_team_name_rejects_invalid(name):
    with pytest.raises(ValueError):
        validate_team_name(name)
