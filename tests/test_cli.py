import pytest
from pipal import cli, runner
from pipal.cli import build_parser, parse_team_member_spec
from pipal.registry import load_registry


def test_parse_team_member_spec():
    assert parse_team_member_spec("ada:Researcher") == ("ada", "Researcher")


def test_parse_team_member_spec_invalid():
    with pytest.raises(ValueError):
        parse_team_member_spec("ada")


def test_parser_agent_create():
    args = build_parser().parse_args(["agent", "create", "momo"])
    assert args.cmd == "agent"
    assert args.agent_cmd == "create"
    assert args.name == "momo"
    assert args.type == "default"


def test_parser_agent_create_kbchat():
    args = build_parser().parse_args(["agent", "create", "erwin", "--type", "kbchat", "--kb", "/tmp/kb"])
    assert args.type == "kbchat"
    assert args.kb_path == "/tmp/kb"


@pytest.mark.parametrize("suffix", [
    ["--provider", "fake"], ["--model", "test"],
    ["--provider", "fake", "--model", "test"],
])
def test_create_rejects_model_defaults_without_side_effects(tmp_path, monkeypatch, suffix):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli, "migrate_registry", lambda: pytest.fail("must validate before migration"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["agent", "create", "momo", str(tmp_path / "agents"), *suffix])
    assert exc.value.code == 2
    assert not (tmp_path / "agents").exists()
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize("command", ["set-llm", "model-status"])
def test_removed_model_configuration_commands(command):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["agent", command, "momo"])


def test_create_needs_no_model_onboarding(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: pytest.fail("must not discover Pi models"))
    agent_path = tmp_path / "agents" / "momo"
    assert cli.main(["agent", "create", "momo", str(tmp_path / "agents")]) == 0
    assert not (agent_path / "llm.json").exists()
    assert (agent_path / "AGENTS.md").exists()
    assert load_registry()["agents"]["momo"] == str(agent_path)


def test_create_failure_rolls_back_scaffold_and_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path / "home"))
    def fail(*args, **kwargs):
        raise OSError("simulated scaffold failure")
    monkeypatch.setattr(cli, "ensure_agent_scaffold", fail)
    agent_path = tmp_path / "agents" / "momo"
    assert cli.main(["agent", "create", "momo", str(tmp_path / "agents")]) == 2
    assert not agent_path.exists()
    assert not (tmp_path / "home" / "agents.json").exists()


def test_create_failure_preserves_existing_agent_files(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path / "home"))
    agent_path = tmp_path / "agents" / "momo"
    agent_path.mkdir(parents=True)
    (agent_path / "custom.md").write_text("keep me")
    (agent_path / "llm.json").write_text('{"provider":"old","model":"old-model"}\n')
    def fail(path, **kwargs):
        (agent_path / "AGENTS.md").write_text("partial scaffold")
        raise OSError("simulated scaffold failure")
    monkeypatch.setattr(cli, "ensure_agent_scaffold", fail)
    assert cli.main(["agent", "create", "momo", str(tmp_path / "agents")]) == 2
    assert (agent_path / "custom.md").read_text() == "keep me"
    assert (agent_path / "llm.json").read_text() == '{"provider":"old","model":"old-model"}\n'
    assert not (agent_path / "AGENTS.md").exists()
    assert not (tmp_path / "home" / "agents.json").exists()


def test_create_ignores_existing_llm_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path / "home"))
    agent_path = tmp_path / "agents" / "momo"
    (agent_path / "llm.json").mkdir(parents=True)
    assert cli.main(["agent", "create", "momo", str(tmp_path / "agents")]) == 0
    assert (agent_path / "llm.json").is_dir()
    assert (agent_path / "AGENTS.md").exists()


@pytest.mark.parametrize("flags", [[], ["--provider", "custom", "--model", "chosen"], ["--model=chosen"], ["--resume"], ["--continue"]])
def test_chat_uses_pi_defaults_and_preserves_flags(tmp_path, monkeypatch, flags):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli, "get_agent", lambda name: {"path": str(tmp_path)})
    calls = []
    monkeypatch.setattr(cli, "run_agent", lambda *args: calls.append(args))
    assert cli.main(["agent", "chat", "momo", *flags]) == 0
    assert calls == [(str(tmp_path), {}, flags)]


def test_session_open_does_not_override_saved_model(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli, "get_agent", lambda name: {"path": str(tmp_path)})
    session = tmp_path / "saved.jsonl"
    session.write_text('{"type":"session"}\n')
    monkeypatch.setattr(cli, "_resolve_session_file", lambda *args: session)
    calls = []
    monkeypatch.setattr(cli, "run_agent", lambda *args: calls.append(args))
    assert cli.main(["session", "open", "--agent", "momo", "saved"]) == 0
    assert calls == [(str(tmp_path), {}, ["--topic", "main", "--session", str(session)])]


def test_legacy_llm_config_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path / "home"))
    (tmp_path / "llm.json").write_text("not valid JSON")
    (tmp_path / "llm.local.json").mkdir()
    monkeypatch.setattr(cli, "get_agent", lambda name: {"path": str(tmp_path)})
    calls = []
    monkeypatch.setattr(cli, "run_agent", lambda *args: calls.append(args))
    assert cli.main(["agent", "chat", "momo"]) == 0
    assert calls == [(str(tmp_path), {}, [])]


@pytest.mark.parametrize("flags", [[], ["--provider", "explicit", "--model", "chosen"], ["--provider=explicit", "--model=chosen"], ["--resume"], ["--session", "saved.jsonl"]])
def test_interactive_runner_ignores_agent_defaults(tmp_path, monkeypatch, flags):
    (tmp_path / "agent.json").write_text('{"type":"kbchat"}')
    monkeypatch.setattr(runner, "_read_agent_type", lambda path: "kbchat")
    calls = []
    monkeypatch.setattr(runner, "_run_agent_cmd", lambda **kwargs: calls.append(kwargs))
    runner.run_agent(str(tmp_path), {"provider": "old", "model": "stale"}, flags)
    launch = calls[0]
    assert launch["llm_config"] == {}
    assert launch["extra_args"][:len(flags)] == flags
    cmd = runner._build_pi_cmd(**{key: launch[key] for key in (
        "agent_path", "llm_config", "extra_args", "system_prompt", "no_session", "topic_name", "resume", "extensions",
    )})
    assert "old" not in cmd and "stale" not in cmd
    assert not any("model_recovery" in arg for arg in cmd)
    if not flags:
        assert "--provider" not in cmd and "--model" not in cmd


def test_launcher_executes_pi_without_model_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_find_native_pi", lambda: "/fake/pi")
    monkeypatch.setattr(runner, "_lock_session_for_exec", lambda cmd: None)
    calls = []
    monkeypatch.setattr(runner.os, "execv", lambda binary, cmd: calls.append((binary, cmd)))
    # Isolate launch environment changes to this test.
    monkeypatch.setattr(runner.os, "environ", dict(runner.os.environ))
    flags = ["--session", "saved.jsonl", "--model=explicit"]
    runner._run_agent_cmd(str(tmp_path), {}, flags, "persona", False, "main", False)
    binary, cmd = calls[0]
    assert binary == "/fake/pi"
    assert cmd[-len(flags):] == flags
    assert "--provider" not in cmd
    assert not any("model_recovery" in arg for arg in cmd)


def test_parser_agent_chat():
    args = build_parser().parse_args(["agent", "chat", "momo"])
    assert args.agent_cmd == "chat"
    assert args.name == "momo"


def test_parser_agent_list():
    assert build_parser().parse_args(["agent", "list"]).agent_cmd == "list"


def test_parser_team_create():
    args = build_parser().parse_args([
        "team", "create", "life-board", "--manager", "sasha",
        "--member", "ada:Researcher", "--member", "raven:Reviewer",
    ])
    assert args.cmd == "team"
    assert args.team_cmd == "create"
    assert args.manager == "sasha"
    assert args.member == ["ada:Researcher", "raven:Reviewer"]


def test_parser_team_chat():
    args = build_parser().parse_args(["team", "chat", "life-board", "--topic", "insurance"])
    assert args.team_cmd == "chat"
    assert args.name == "life-board"
    assert args.topic == "insurance"


def test_parser_serve():
    args = build_parser().parse_args(["serve", "--port", "9000", "--read-only"])
    assert args.cmd == "serve"
    assert args.host == "127.0.0.1"
    assert args.port == 9000
    assert args.read_only is True


def test_parser_topic_summarize():
    args = build_parser().parse_args(["topic", "summarize", "--agent", "momo", "--topic", "work"])
    assert args.cmd == "topic"
    assert args.topic_cmd == "summarize"
    assert args.topic_name == "work"


def test_parser_session_list():
    args = build_parser().parse_args(["session", "list", "--agent", "momo", "--topic", "work"])
    assert args.cmd == "session"
    assert args.session_cmd == "list"
    assert args.topic == "work"
