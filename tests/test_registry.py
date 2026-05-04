import json
import pytest
from pathlib import Path
from pipal.registry import (
    add_agent,
    rm_agent,
    list_agents,
    get_agent,
    load_registry,
    registry_path,
)


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """Redirect all registry operations to a temp directory."""
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path))


def test_add_and_get_agent(tmp_path):
    agent_path = str(tmp_path / "agents" / "alice")
    result = add_agent("alice", agent_path)
    assert result["path"] == agent_path

    agent = get_agent("alice")
    assert agent is not None
    assert agent["name"] == "alice"
    assert agent["path"] == agent_path


def test_add_creates_registry_if_missing(tmp_path):
    assert not registry_path().exists()
    add_agent("bob", str(tmp_path / "bob"))
    assert registry_path().exists()


def test_list_agents(tmp_path):
    assert list_agents() == {}
    add_agent("a", str(tmp_path / "a"))
    add_agent("b", str(tmp_path / "b"))
    agents = list_agents()
    assert set(agents.keys()) == {"a", "b"}


def test_remove_agent(tmp_path):
    add_agent("charlie", str(tmp_path / "charlie"))
    path = rm_agent("charlie")
    assert path is not None
    assert get_agent("charlie") is None


def test_remove_nonexistent_agent():
    path = rm_agent("nonexistent")
    assert path is None


def test_get_nonexistent_agent():
    assert get_agent("nonexistent") is None


def test_add_overwrites_existing(tmp_path):
    add_agent("dave", str(tmp_path / "old"))
    add_agent("dave", str(tmp_path / "new"))
    agent = get_agent("dave")
    assert "new" in agent["path"]


def test_load_registry_handles_invalid_json(tmp_path):
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not-json", encoding="utf-8")

    reg = load_registry()
    assert reg == {"agents": {}}


def test_load_registry_handles_non_mapping_payload(tmp_path):
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(["not", "a", "dict"]))

    reg = load_registry()
    assert reg == {"agents": {}}


def test_load_registry_migrates_legacy_pal_paths(tmp_path, monkeypatch):
    old_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: old_home)
    monkeypatch.setenv("PIPAL_HOME", str(old_home / ".pipal"))

    reg_path = old_home / ".pipal" / "agents.json"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path = str((old_home / ".pal" / "agents" / "momo").resolve())
    reg_path.write_text(json.dumps({"agents": {"momo": legacy_path}}), encoding="utf-8")

    reg = load_registry()
    assert reg["agents"]["momo"].startswith("agents/")
    agent = get_agent("momo")
    assert agent is not None
    assert str(old_home / ".pipal" / "agents" / "momo") == agent["path"]
