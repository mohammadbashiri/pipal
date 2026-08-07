import json

import pytest

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

    assert remove_team("life-board") is True
    assert load_team("life-board") is None
    assert remove_team("life-board") is False


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
