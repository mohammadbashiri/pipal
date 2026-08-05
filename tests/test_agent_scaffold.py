import pytest
from pathlib import Path
from pipal.agent_scaffold import ensure_agent_scaffold, AGENT_FILES


@pytest.fixture
def agent_dir(tmp_path):
    return tmp_path / "test-agent"


def test_default_creates_expected_files(agent_dir):
    ensure_agent_scaffold(str(agent_dir), name="testy", template="default")
    for fname in ["AGENTS.md", "IDENTITY.md", "POLICY.md", "USER.md", "MEMORY.md"]:
        assert (agent_dir / fname).exists(), f"{fname} missing"
    assert (agent_dir / "topics").is_dir()


def test_default_substitutes_name(agent_dir):
    ensure_agent_scaffold(str(agent_dir), name="testy", template="default")
    identity = (agent_dir / "IDENTITY.md").read_text()
    assert "testy" in identity
    assert "{name}" not in identity


def test_default_substitutes_agent_path(agent_dir):
    ensure_agent_scaffold(str(agent_dir), name="testy", template="default")
    agents_md = (agent_dir / "AGENTS.md").read_text()
    assert str(agent_dir.resolve()) in agents_md
    assert "{agent_path}" not in agents_md


def test_default_creates_onboarding(agent_dir):
    ensure_agent_scaffold(str(agent_dir), name="testy", template="default")
    onboarding = agent_dir / "onboarding.md"
    assert onboarding.exists()
    content = onboarding.read_text()
    assert "- [ ]" in content


def test_kbchat_creates_expected_files(agent_dir):
    ensure_agent_scaffold(
        str(agent_dir), name="erwin", template="kbchat",
        kb_path="/tmp/kb", agent_type="kbchat",
    )
    for fname in ["AGENTS.md", "IDENTITY.md", "POLICY.md", "MEMORY.md", "KB.md"]:
        assert (agent_dir / fname).exists(), f"{fname} missing"


def test_kbchat_no_onboarding(agent_dir):
    ensure_agent_scaffold(
        str(agent_dir), name="erwin", template="kbchat",
        kb_path="/tmp/kb", agent_type="kbchat",
    )
    assert not (agent_dir / "onboarding.md").exists()


def test_kbchat_substitutes_kb_path(agent_dir):
    ensure_agent_scaffold(
        str(agent_dir), name="erwin", template="kbchat",
        kb_path="/tmp/my_kb", agent_type="kbchat",
    )
    kb_md = (agent_dir / "KB.md").read_text()
    assert "/tmp/my_kb" in kb_md
    assert "{kb_path}" not in kb_md


def test_kbchat_writes_type_file(agent_dir):
    ensure_agent_scaffold(
        str(agent_dir), name="erwin", template="kbchat",
        kb_path="/tmp/kb", agent_type="kbchat",
    )
    type_file = agent_dir / ".pipal_type"
    assert type_file.exists()
    assert type_file.read_text().strip() == "kbchat"


def test_default_no_type_file(agent_dir):
    ensure_agent_scaffold(str(agent_dir), name="testy", template="default")
    assert not (agent_dir / ".pipal_type").exists()


def test_does_not_overwrite_existing_files(agent_dir):
    agent_dir.mkdir(parents=True)
    (agent_dir / "IDENTITY.md").write_text("custom content")
    ensure_agent_scaffold(str(agent_dir), name="testy", template="default")
    assert (agent_dir / "IDENTITY.md").read_text() == "custom content"
