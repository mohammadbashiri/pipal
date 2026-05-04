from pipal.check_pi_compatibility import (
    REQUIRED_FLAGS,
    REMEDIATION,
    _check_flag_presence,
    _check_prompt_flag,
    _check_rpc_mode,
)


def test_check_flag_presence_all_present():
    help_text = " ".join(REQUIRED_FLAGS)
    assert _check_flag_presence(help_text, REQUIRED_FLAGS) == []


def test_check_flag_presence_reports_missing():
    help_text = "--mode --session"
    missing = _check_flag_presence(help_text, REQUIRED_FLAGS)
    assert "--append-system-prompt" in missing
    assert "--tools" in missing


def test_check_prompt_flag_supports_short_and_long():
    assert _check_prompt_flag("Usage: pi -p <prompt>") is True
    assert _check_prompt_flag("Usage: pi --prompt <prompt>") is True
    assert _check_prompt_flag("Usage: pi --help") is False


def test_check_rpc_mode_detects_rpc_word_case_insensitive():
    assert _check_rpc_mode("Run in RPC mode") is True
    assert _check_rpc_mode("no mention") is False


def test_remediation_has_entries_for_all_core_checks():
    expected = {
        "pi binary",
        "pi --version",
        "pi --help",
        "required flags",
        "prompt flag",
        "rpc mode",
        "rpc start",
    }
    assert expected.issubset(set(REMEDIATION))
