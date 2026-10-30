from types import SimpleNamespace

import pytest

from pipal import topic_summary
from pipal.server_config import ServerSettings
from pipal.server_rpc import PiRpcClient


@pytest.mark.parametrize("override", [{}, {"model": "chosen"}, {"provider": "explicit", "model": "chosen"}])
def test_rpc_only_passes_explicit_model_flags(tmp_path, override):
    # A legacy agent default must have no effect on an RPC launch.
    (tmp_path / "llm.json").write_text('{"provider":"legacy","model":"retired"}')
    client = PiRpcClient(
        settings=ServerSettings(auth_token=None, cors_origins=(), pipal_extensions_dir=None, pi_bin="pi"),
        agent_dir=tmp_path, topic_name="main", llm_config=override,
    )
    command = client._build_cmd()
    for key in ("provider", "model"):
        if key in override:
            assert command[command.index(f"--{key}") + 1] == override[key]
        else:
            assert f"--{key}" not in command


@pytest.mark.parametrize("provider,model", [(None, None), (None, "chosen"), ("explicit", "chosen")])
def test_summary_lets_pi_select_defaults(monkeypatch, provider, model):
    commands = []
    monkeypatch.setattr(topic_summary, "_find_native_pi", lambda: "pi")
    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout="summary", stderr="", returncode=0)
    monkeypatch.setattr(topic_summary.subprocess, "run", run)
    assert topic_summary._run_pi_summary("summarize", provider, model) == "summary"
    command = commands[0]
    assert ("--provider" in command) == bool(provider)
    assert ("--model" in command) == bool(model)
