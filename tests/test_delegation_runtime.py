import json
from pathlib import Path

from pipal import delegation_runtime


def test_build_delegation_runtime_creates_persistent_threads(tmp_path, monkeypatch):
    primary = tmp_path / "agents" / "sasha"
    ada = tmp_path / "agents" / "ada"
    raven = tmp_path / "agents" / "raven"
    for path in (primary, ada, raven):
        path.mkdir(parents=True)

    monkeypatch.setattr(
        delegation_runtime,
        "list_agents",
        lambda: {"sasha": str(primary), "ada": str(ada), "raven": str(raven)},
    )
    monkeypatch.setattr(
        delegation_runtime,
        "load_llm_config",
        lambda path: {"provider": "test", "model": f"model-{Path(path).name}"},
    )
    monkeypatch.setattr(
        delegation_runtime,
        "load_persona",
        lambda path: f"Persona for {Path(path).name}",
    )
    monkeypatch.setattr(delegation_runtime, "_find_native_pi", lambda: "/fake/pi")
    monkeypatch.setattr(
        delegation_runtime,
        "list_teams",
        lambda: [{
            "name": "research",
            "manager": "sasha",
            "members": [
                {"agent": "sasha", "role": "Manager"},
                {"agent": "ada", "role": "Researcher"},
                {"agent": "missing", "role": "Reviewer"},
            ],
        }],
    )

    cwd = tmp_path / "project"
    cwd.mkdir()
    runtime, runtime_file = delegation_runtime.build_delegation_runtime(
        "sasha",
        str(primary),
        "main",
        working_dir=cwd,
    )

    assert runtime_file.is_file()
    assert runtime["primary"] == "sasha"
    assert runtime["working_dir"] == str(cwd)
    assert [item["agent"] for item in runtime["delegates"]] == ["ada", "raven"]
    assert runtime["teams"] == [{
        "name": "research",
        "manager": "sasha",
        "members": [
            {"agent": "sasha", "role": "Manager"},
            {"agent": "ada", "role": "Researcher"},
        ],
    }]
    assert all(item["agent"] != "sasha" for item in runtime["delegates"])
    for item in runtime["delegates"]:
        assert Path(item["transcript_file"]).is_file()
        prompt = Path(item["prompt_file"]).read_text(encoding="utf-8")
        assert "persistent Pipal agent" in prompt
        assert str(cwd) in prompt

    ada_runtime = next(item for item in runtime["delegates"] if item["agent"] == "ada")
    session = Path(ada_runtime["session_file"])
    session.write_text(
        json.dumps(
            {
                "type": "session",
                "version": 3,
                "id": "ada-session",
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": str(cwd),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    resumed, _ = delegation_runtime.build_delegation_runtime(
        "sasha",
        str(primary),
        "main",
        working_dir=cwd,
    )
    resumed_ada = next(item for item in resumed["delegates"] if item["agent"] == "ada")
    assert resumed_ada["session_file"] == str(session.resolve())
