import pytest
from pathlib import Path
from pipal.agent_scaffold import ensure_agent_scaffold
from pipal.runner import load_persona, _read_agent_type, _onboarding_complete


@pytest.fixture
def default_agent(tmp_path):
    agent_dir = tmp_path / "default-agent"
    ensure_agent_scaffold(str(agent_dir), name="testy", template="default")
    return agent_dir


@pytest.fixture
def kbchat_agent(tmp_path):
    agent_dir = tmp_path / "kb-agent"
    ensure_agent_scaffold(
        str(agent_dir), name="erwin", template="kbchat",
        kb_path="/tmp/kb", agent_type="kbchat",
    )
    return agent_dir


# ── _read_agent_type ─────────────────────────────────────────────

def test_read_agent_type_default(default_agent):
    assert _read_agent_type(default_agent) is None


def test_read_agent_type_kbchat(kbchat_agent):
    assert _read_agent_type(kbchat_agent) == "kbchat"


def test_read_agent_type_missing(tmp_path):
    assert _read_agent_type(tmp_path) is None


# ── _onboarding_complete ─────────────────────────────────────────

def test_onboarding_incomplete(default_agent):
    assert _onboarding_complete(default_agent) is False


def test_onboarding_complete_all_checked(default_agent):
    onboarding = default_agent / "onboarding.md"
    content = onboarding.read_text()
    content = content.replace("- [ ]", "- [x]")
    onboarding.write_text(content)
    assert _onboarding_complete(default_agent) is True


def test_onboarding_complete_no_file_no_marker(tmp_path):
    assert _onboarding_complete(tmp_path) is False


def test_onboarding_complete_init_marker(tmp_path):
    (tmp_path / ".pipal_initialized").write_text("initialized\n")
    assert _onboarding_complete(tmp_path) is True


# ── load_persona ─────────────────────────────────────────────────

def test_load_persona_default_includes_onboarding(default_agent):
    persona = load_persona(str(default_agent))
    assert "onboarding" in persona.lower() or "- [ ]" in persona


def test_load_persona_default_excludes_onboarding_when_complete(default_agent):
    onboarding = default_agent / "onboarding.md"
    content = onboarding.read_text()
    content = content.replace("- [ ]", "- [x]")
    onboarding.write_text(content)
    persona = load_persona(str(default_agent))
    assert "- [ ]" not in persona


def test_load_persona_kbchat_no_onboarding(kbchat_agent):
    persona = load_persona(str(kbchat_agent))
    assert "- [ ]" not in persona
    assert "onboarding" not in persona.lower()


def test_load_persona_includes_core_files(default_agent):
    persona = load_persona(str(default_agent))
    assert "AGENTS.md" in persona
    assert "IDENTITY.md" in persona


def test_load_persona_kbchat_includes_kb(kbchat_agent):
    persona = load_persona(str(kbchat_agent))
    assert "/tmp/kb" in persona
