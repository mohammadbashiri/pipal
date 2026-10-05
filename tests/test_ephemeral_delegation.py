import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pipal import delegation_runtime
from pipal.cli import build_parser
from pipal.runner import _build_pi_cmd, _session_llm_config, build_pipal_context


ESBUILD = Path("/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/esbuild")
HARNESS = Path(__file__).with_name("ephemeral_harness.cjs")


def test_runtime_exposes_ephemeral_workers_without_registered_delegates(monkeypatch, tmp_path):
    monkeypatch.setattr(delegation_runtime, "list_agents", lambda: {})
    monkeypatch.setattr(delegation_runtime, "list_teams", lambda: [])
    monkeypatch.setattr(delegation_runtime, "_find_native_pi", lambda: "pi")
    primary = tmp_path / "primary"
    primary.mkdir()

    runtime, path = delegation_runtime.build_delegation_runtime(
        "momo", str(primary), "pipal", working_dir=tmp_path,
        primary_llm={"provider": "openai-codex", "model": "session-model"},
    )

    assert runtime["delegates"] == []
    assert runtime["default_provider"] == "openai-codex"
    assert runtime["default_model"] == "session-model"
    assert runtime["ephemeral_root"] == str(primary / "topics/pipal/delegations/ephemeral")
    assert path.is_file()


def test_chat_model_flags_override_only_the_session(tmp_path):
    args = build_parser().parse_args(["agent", "chat", "reviewer", "--model", "temporary-model"])
    assert args.args == ["--model", "temporary-model"]
    saved = {"provider": "openai-codex", "model": "saved-model"}
    command = _build_pi_cmd(str(tmp_path), saved, args.args, True, "main", None, include_extension=False)
    assert command == ["pi", "--provider", "openai-codex", "--model", "saved-model", "--no-session", "--model", "temporary-model"]
    assert saved["model"] == "saved-model"
    assert _session_llm_config(saved, args.args) == {"provider": "openai-codex", "model": "temporary-model"}
    assert _session_llm_config(saved, ["--provider=other", "--model=second"]) == {"provider": "other", "model": "second"}
    assert "not Pi's separate `subagent`" in build_pipal_context(tmp_path, "main")


@pytest.mark.skipif(not shutil.which("node") or not ESBUILD.is_dir(), reason="Pi's Node/esbuild runtime unavailable")
def test_ephemeral_and_persistent_override_lifecycles():
    result = subprocess.run(
        ["node", str(HARNESS)],
        env={**os.environ, "PIPAL_ESBUILD": str(ESBUILD), "PIPAL_PYTHON": sys.executable},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "ephemeral and persistent override lifecycles ok" in result.stdout
