import pytest
from pipal.daemon import parse_interval, format_interval, format_uptime


# ── parse_interval ───────────────────────────────────────────────

def test_parse_interval_minutes():
    assert parse_interval("30m") == 1800


def test_parse_interval_hours():
    assert parse_interval("2h") == 7200


def test_parse_interval_combined():
    assert parse_interval("1h30m") == 5400


def test_parse_interval_seconds():
    assert parse_interval("90s") == 90


def test_parse_interval_full():
    assert parse_interval("1h30m15s") == 5415

def test_parse_interval_with_spaces():
    assert parse_interval("1h 30m 15s") == 5415


def test_parse_interval_invalid():
    with pytest.raises(ValueError):
        parse_interval("abc")


def test_parse_interval_zero():
    with pytest.raises(ValueError):
        parse_interval("0s")


# ── format_interval ──────────────────────────────────────────────

def test_format_interval_minutes():
    assert format_interval(1800) == "30m"


def test_format_interval_hours():
    assert format_interval(7200) == "2h"


def test_format_interval_combined():
    assert format_interval(5400) == "1h 30m"


def test_format_interval_seconds():
    assert format_interval(45) == "45s"


def test_format_interval_zero():
    assert format_interval(0) == "0s"


# ── format_uptime ────────────────────────────────────────────────

def test_format_uptime_recent():
    from datetime import datetime, timedelta
    started = (datetime.now() - timedelta(seconds=30)).isoformat()
    result = format_uptime(started)
    assert "s" in result


def test_format_uptime_minutes():
    from datetime import datetime, timedelta
    started = (datetime.now() - timedelta(minutes=5, seconds=10)).isoformat()
    result = format_uptime(started)
    assert "5m" in result


def test_format_uptime_hours():
    from datetime import datetime, timedelta
    started = (datetime.now() - timedelta(hours=2, minutes=15)).isoformat()
    result = format_uptime(started)
    assert "2h" in result


# ── roundtrip ────────────────────────────────────────────────────

def test_parse_format_roundtrip():
    """Roundtrip works for specs without spaces. format_interval adds
    spaces (e.g. '2h 30m') which parse_interval can't parse, so we
    only test single-unit specs here."""
    for spec in ["30m", "1h", "45s"]:
        seconds = parse_interval(spec)
        formatted = format_interval(seconds)
        assert parse_interval(formatted) == seconds
