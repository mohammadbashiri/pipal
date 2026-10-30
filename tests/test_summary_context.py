import pytest

from pipal.cli import build_parser
from pipal.runner import _extension_paths, build_pipal_context, load_persona


def test_summary_is_an_optional_on_demand_reference(tmp_path):
    topic = tmp_path / "topics" / "work"
    sessions = topic / "sessions"
    sessions.mkdir(parents=True)
    notes = topic / "summary.md"
    notes.write_text("UNIQUE_EXISTING_SUMMARY_CONTENT")
    previous = sessions / "previous.jsonl"
    previous.write_text("UNIQUE_PREVIOUS_CONVERSATION_CONTENT")
    context = build_pipal_context(tmp_path, "work")
    assert str(notes) in context
    assert str(sessions) in context
    assert "on demand, not automatically loaded" in context
    assert "owner's agreement" in context
    assert "no mandatory question" in context
    assert "branch entry ID or timestamp" in context
    assert "resumed session can contain newer" in context
    assert "historical artifacts" in context
    for content in (notes.read_text(), previous.read_text()):
        assert content not in context
        assert content not in load_persona(str(tmp_path))
    assert not (topic / "summary.state.json").exists()
    assert not (topic / "summary.log").exists()


@pytest.mark.parametrize("agent_type", [None, "kbchat"])
def test_all_agent_types_get_the_summary_shortcut_without_shutdown_hooks(agent_type):
    names = [path.name for path in _extension_paths(agent_type)]
    assert "commands.ts" in names
    assert "rolling_summary.ts" not in names


def test_automatic_summarizer_cli_is_retired():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["topic", "summarize", "--agent", "fixture"])
    assert exc.value.code == 2
