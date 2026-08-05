"""Integration tests — skipped unless dependencies are available.

Run with: uv run pytest -m integration
"""

import json
import shutil
import subprocess
import pytest
from pathlib import Path

from pipal.agent_scaffold import ensure_agent_scaffold, write_llm_json
from pipal.runner import (
    _build_pi_cmd,
    _find_native_pi,
    _read_agent_type,
    _strip_tool_flags,
    _extract_topic_name,
    _extension_paths,
    load_persona,
)
from pipal.registry import add_agent, rm_agent, pipal_dir


# ── markers & fixtures ───────────────────────────────────────────

pytestmark = pytest.mark.integration


def _has_pi():
    try:
        _find_native_pi()
        return True
    except FileNotFoundError:
        return False


def _has_pipal():
    return shutil.which("pipal") is not None


requires_pi = pytest.mark.skipif(not _has_pi(), reason="pi binary not found")
requires_pipal = pytest.mark.skipif(not _has_pipal(), reason="pipal binary not found")


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Isolated PIPAL_HOME for integration tests."""
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def default_agent(isolated_env):
    """Create a fully scaffolded default agent."""
    agent_dir = isolated_env / "agents" / "test-default"
    ensure_agent_scaffold(str(agent_dir), name="test-default", template="default")
    add_agent("test-default", str(agent_dir))
    return agent_dir


@pytest.fixture
def kbchat_agent(isolated_env, tmp_path):
    """Create a fully scaffolded kbchat agent with a dummy KB."""
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "README.md").write_text("# Test KB\n\nThis is about testing.")
    (kb_dir / "topic_a.md").write_text("# Topic A\n\nDetails about topic A.")

    agent_dir = isolated_env / "agents" / "test-kb"
    ensure_agent_scaffold(
        str(agent_dir), name="test-kb", template="kbchat",
        kb_path=str(kb_dir), agent_type="kbchat",
    )
    add_agent("test-kb", str(agent_dir))
    return agent_dir


# ── _build_pi_cmd tests (no pi needed) ──────────────────────────

class TestBuildPiCmd:
    """Test command construction without executing pi."""

    def test_basic_cmd(self, default_agent):
        cmd = _build_pi_cmd(
            agent_path=str(default_agent),
            llm_config={"provider": "anthropic", "model": "claude-opus-4-6"},
            extra_args=[],
            no_session=True,
            topic_name="main",
            system_prompt="test prompt",
        )
        assert cmd[0] == "pi"
        assert "--provider" in cmd
        assert "anthropic" in cmd
        assert "--model" in cmd
        assert "claude-opus-4-6" in cmd
        assert "--no-session" in cmd
        assert "--append-system-prompt" in cmd

    def test_session_file_created(self, default_agent):
        cmd = _build_pi_cmd(
            agent_path=str(default_agent),
            llm_config={"provider": "ollama", "model": "test"},
            extra_args=[],
            no_session=False,
            topic_name="main",
            system_prompt=None,
        )
        assert "--session" in cmd
        session_idx = cmd.index("--session")
        session_file = cmd[session_idx + 1]
        assert "topics/main/sessions/" in session_file
        assert session_file.endswith(".jsonl")

    def test_extensions_included(self, default_agent):
        cmd = _build_pi_cmd(
            agent_path=str(default_agent),
            llm_config={},
            extra_args=[],
            no_session=True,
            topic_name="main",
            system_prompt=None,
            include_extension=True,
        )
        ext_count = cmd.count("--extension")
        assert ext_count >= 1

    def test_extensions_excluded(self, default_agent):
        cmd = _build_pi_cmd(
            agent_path=str(default_agent),
            llm_config={},
            extra_args=[],
            no_session=True,
            topic_name="main",
            system_prompt=None,
            include_extension=False,
        )
        assert "--extension" not in cmd

    def test_kbchat_extensions(self, kbchat_agent):
        agent_type = _read_agent_type(kbchat_agent)
        extensions = _extension_paths(agent_type)
        assert any("kbchat_greet" in str(e) for e in extensions)

    def test_extra_args_passed_through(self, default_agent):
        cmd = _build_pi_cmd(
            agent_path=str(default_agent),
            llm_config={},
            extra_args=["-p", "hello world"],
            no_session=True,
            topic_name="main",
            system_prompt=None,
        )
        assert "-p" in cmd
        assert "hello world" in cmd

    def test_explicit_native_session_is_not_overridden(self, default_agent):
        cmd = _build_pi_cmd(
            agent_path=str(default_agent),
            llm_config={},
            extra_args=["--session", "/tmp/native.jsonl"],
            no_session=False,
            topic_name="main",
            system_prompt=None,
        )
        assert cmd.count("--session") == 1
        assert cmd[-2:] == ["--session", "/tmp/native.jsonl"]


# ── helper function tests ────────────────────────────────────────

class TestRunnerHelpers:

    def test_strip_tool_flags(self):
        args = ["--tools", "read,write", "hello", "--no-tools", "world"]
        result = _strip_tool_flags(args)
        assert result == ["hello", "world"]

    def test_strip_tool_flags_empty(self):
        assert _strip_tool_flags([]) == []

    def test_extract_topic_name_default(self):
        name, remaining = _extract_topic_name(["--foo", "bar"])
        assert name == "main"
        assert remaining == ["--foo", "bar"]

    def test_extract_topic_name_custom(self):
        name, remaining = _extract_topic_name(["--topic", "dev", "--foo"])
        assert name == "dev"
        assert remaining == ["--foo"]

    def test_native_session_flag_passes_through(self):
        name, remaining = _extract_topic_name(["--session", "native.jsonl"])
        assert name == "main"
        assert remaining == ["--session", "native.jsonl"]

    def test_extension_paths_default(self):
        paths = _extension_paths(None)
        assert any("auto_greet" in str(p) for p in paths)
        assert any("rolling_summary" in str(p) for p in paths)

    def test_extension_paths_kbchat(self):
        paths = _extension_paths("kbchat")
        assert any("kbchat_greet" in str(p) for p in paths)
        assert not any("auto_greet" in str(p) for p in paths)


# ── persona loading integration ──────────────────────────────────

class TestPersonaIntegration:

    def test_default_persona_has_all_sections(self, default_agent):
        persona = load_persona(str(default_agent))
        assert "AGENTS.md" in persona
        assert "IDENTITY.md" in persona
        assert "POLICY.md" in persona
        assert "USER.md" in persona
        assert "MEMORY.md" in persona

    def test_kbchat_persona_has_kb_path(self, kbchat_agent):
        persona = load_persona(str(kbchat_agent))
        assert "Knowledge Base" in persona

    def test_kbchat_persona_has_tool_instructions(self, kbchat_agent):
        persona = load_persona(str(kbchat_agent))
        assert "ALWAYS use tools" in persona

    def test_default_persona_with_summary(self, default_agent):
        summary_dir = default_agent / "topics" / "main"
        summary_dir.mkdir(parents=True)
        (summary_dir / "summary.md").write_text("## Goal\nTest the system")
        # Summary is loaded separately in run_agent, not in load_persona
        # Just verify the file is there
        assert (summary_dir / "summary.md").exists()


# ── session file parsing ─────────────────────────────────────────

class TestSessionParsing:

    def test_parse_session_jsonl(self, default_agent):
        """Verify we can create and read back session entries."""
        session_dir = default_agent / "topics" / "main" / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_file = session_dir / "test.jsonl"

        entries = [
            {"type": "message", "message": {"role": "user", "content": "hello"}},
            {"type": "message", "message": {"role": "assistant", "content": "hi there"}},
        ]
        with session_file.open("w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        lines = session_file.read_text().splitlines()
        parsed = [json.loads(line) for line in lines if line.strip()]
        assert len(parsed) == 2
        assert parsed[0]["message"]["role"] == "user"
        assert parsed[1]["message"]["role"] == "assistant"


# ── server endpoint tests (no LLM needed) ────────────────────────

class TestServerEndpoints:

    @pytest.fixture
    def client(self, default_agent, isolated_env):
        from fastapi.testclient import TestClient
        from pipal.server import create_app
        app = create_app()
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_list_agents(self, client):
        resp = client.get("/agents")
        assert resp.status_code == 200
        agents = resp.json()
        names = [a["name"] for a in agents]
        assert "test-default" in names

    def test_get_sessions_empty(self, client):
        resp = client.get("/agents/test-default/topics")
        assert resp.status_code == 200

    def test_get_sessions_unknown_agent(self, client):
        resp = client.get("/agents/nonexistent/topics")
        assert resp.status_code == 404

    def test_create_topic(self, client):
        resp = client.post("/agents/test-default/topics")
        assert resp.status_code == 200
        assert "name" in resp.json()

    def test_create_session_read_only(self, default_agent, isolated_env):
        from fastapi.testclient import TestClient
        from pipal.server import create_app
        app = create_app(read_only=True)
        client = TestClient(app)
        resp = client.post("/agents/test-default/topics")
        assert resp.status_code == 403

    def test_session_history(self, client, default_agent):
        # Create a session with some content
        session_dir = default_agent / "topics" / "test-topic" / "sessions"
        session_dir.mkdir(parents=True)
        session_file = session_dir / "20260101-000000.jsonl"
        entries = [
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]}},
            {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}},
        ]
        with session_file.open("w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        resp = client.get("/agents/test-default/topics/test-topic/history")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

        sessions_resp = client.get("/agents/test-default/topics/test-topic/sessions")
        assert sessions_resp.status_code == 200
        assert sessions_resp.json() == [{"name": "20260101-000000.jsonl"}]

        session_resp = client.get(
            "/agents/test-default/topics/test-topic/sessions/20260101-000000.jsonl/history"
        )
        assert session_resp.status_code == 200
        assert session_resp.json()["messages"] == messages


# ── pi binary tests (needs pi installed) ─────────────────────────

class TestPiBinary:

    @requires_pi
    def test_find_native_pi(self):
        pi_bin = _find_native_pi()
        assert Path(pi_bin).exists()

    @requires_pi
    def test_pi_version(self):
        pi_bin = _find_native_pi()
        result = subprocess.run([pi_bin, "--version"], capture_output=True, text=True)
        assert result.returncode == 0
        output = (result.stdout or result.stderr).strip()
        assert output

    @requires_pi
    def test_pi_has_required_flags(self):
        pi_bin = _find_native_pi()
        result = subprocess.run([pi_bin, "--help"], capture_output=True, text=True)
        help_text = (result.stdout or "") + (result.stderr or "")
        for flag in ["--mode", "--session", "--extension", "--append-system-prompt"]:
            assert flag in help_text, f"Missing flag: {flag}"


# ── pipal CLI integration (needs pipal installed) ─────────────────

class TestPipalCLI:

    @requires_pipal
    def test_pipal_help(self):
        result = subprocess.run(["pipal", "--help"], capture_output=True, text=True)
        assert result.returncode == 0

    @requires_pipal
    def test_pipal_agent_list(self):
        result = subprocess.run(["pipal", "agent", "list"], capture_output=True, text=True)
        assert result.returncode == 0
