import pytest
from pipal.cli import build_parser, parse_llm_spec


# ── parse_llm_spec ───────────────────────────────────────────────

def test_parse_llm_spec_valid():
    provider, model = parse_llm_spec("anthropic:claude-opus-4-6")
    assert provider == "anthropic"
    assert model == "claude-opus-4-6"


def test_parse_llm_spec_ollama():
    provider, model = parse_llm_spec("ollama:Mistral:7b")
    assert provider == "ollama"
    assert model == "Mistral:7b"


def test_parse_llm_spec_no_colon():
    with pytest.raises(ValueError):
        parse_llm_spec("justprovider")


def test_parse_llm_spec_empty():
    with pytest.raises(ValueError):
        parse_llm_spec("")


def test_parse_llm_spec_missing_model():
    with pytest.raises(ValueError):
        parse_llm_spec("provider:")


def test_parse_llm_spec_missing_provider():
    with pytest.raises(ValueError):
        parse_llm_spec(":model")


# ── build_parser ─────────────────────────────────────────────────

def test_parser_agent_create():
    p = build_parser()
    args = p.parse_args(["agent", "create", "momo"])
    assert args.cmd == "agent"
    assert args.agent_cmd == "create"
    assert args.name == "momo"
    assert args.type == "default"


def test_parser_agent_create_kbchat():
    p = build_parser()
    args = p.parse_args(["agent", "create", "erwin", "--type", "kbchat", "--kb", "/tmp/kb"])
    assert args.type == "kbchat"
    assert args.kb_path == "/tmp/kb"


def test_parser_agent_chat():
    p = build_parser()
    args = p.parse_args(["agent", "chat", "momo"])
    assert args.agent_cmd == "chat"
    assert args.name == "momo"


def test_parser_agent_list():
    p = build_parser()
    args = p.parse_args(["agent", "list"])
    assert args.agent_cmd == "list"


def test_parser_task_list():
    p = build_parser()
    args = p.parse_args(["task", "list", "--agent", "momo"])
    assert args.cmd == "task"
    assert args.task_cmd == "list"
    assert args.agent == "momo"


def test_parser_daemon_start():
    p = build_parser()
    args = p.parse_args(["daemon", "start", "--agent", "momo", "--every", "30m"])
    assert args.cmd == "daemon"
    assert args.daemon_cmd == "start"
    assert args.every == "30m"


def test_parser_serve():
    p = build_parser()
    args = p.parse_args(["serve", "--port", "9000", "--read-only"])
    assert args.cmd == "serve"
    assert args.port == 9000
    assert args.read_only is True


def test_parser_session_summarize():
    p = build_parser()
    args = p.parse_args(["session", "summarize", "--agent", "momo"])
    assert args.cmd == "session"
    assert args.session_cmd == "summarize"
    assert args.agent == "momo"
