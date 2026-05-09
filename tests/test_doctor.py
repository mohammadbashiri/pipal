from pipal.check_pi_compatibility import (
    MIN_PI_VERSION,
    REQUIRED_FLAGS,
    REMEDIATION,
    _check_flag_presence,
    _check_prompt_flag,
    _check_rpc_mode,
    _extract_semver,
    _is_version_at_least,
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


def test_extract_semver():
    assert _extract_semver("0.66.1") == (0, 66, 1)
    assert _extract_semver("pi version 1.2.3 (build)") == (1, 2, 3)
    assert _extract_semver("unknown") is None


def test_is_version_at_least():
    assert _is_version_at_least("0.66.1", "0.66.1") is True
    assert _is_version_at_least("0.67.0", "0.66.1") is True
    assert _is_version_at_least("0.65.9", "0.66.1") is False
    assert _is_version_at_least("v1.0.0", "0.66.1") is True


def test_remediation_has_entries_for_all_core_checks():
    expected = {
        "pi binary",
        "pi --version",
        "pi version supported",
        "pi --help",
        "required flags",
        "prompt flag",
        "rpc mode",
        "rpc start",
    }
    assert expected.issubset(set(REMEDIATION))
    assert MIN_PI_VERSION in " ".join(REMEDIATION["pi version supported"])
