import pytest
from datetime import datetime, timedelta
from pathlib import Path
from pipal.tasks import (
    _slugify,
    task_id_from_title,
    schedule_seconds,
    is_task_due,
    create_task,
    list_tasks,
    load_task,
    append_run_log,
    last_run,
    remove_task,
    parse_task_response,
    parse_task_message,
    _parse_frontmatter,
)


# ── slugify ──────────────────────────────────────────────────────

def test_slugify_basic():
    assert _slugify("Hello World") == "hello-world"


def test_slugify_special_chars():
    assert _slugify("Check email! (daily)") == "check-email-daily"


def test_slugify_extra_spaces():
    assert _slugify("  lots   of   spaces  ") == "lots-of-spaces"


def test_task_id_from_title():
    assert task_id_from_title("My Cool Task") == "my-cool-task"


# ── schedule_seconds ─────────────────────────────────────────────

def test_schedule_seconds_minutes():
    assert schedule_seconds("every 30m") == 1800


def test_schedule_seconds_hours():
    assert schedule_seconds("every 2h") == 7200


def test_schedule_seconds_combined():
    assert schedule_seconds("every 1h30m") == 5400

def test_schedule_seconds_combined_with_spaces():
    assert schedule_seconds("every 1h 30m") == 5400


def test_schedule_seconds_days():
    assert schedule_seconds("every 1d") == 86400


def test_schedule_seconds_weeks():
    assert schedule_seconds("every 1w") == 604800


def test_schedule_seconds_none():
    assert schedule_seconds(None) is None


def test_schedule_seconds_invalid():
    assert schedule_seconds("whenever") is None


# ── is_task_due ──────────────────────────────────────────────────

def test_is_task_due_no_schedule(tmp_path):
    task = {"schedule": None}
    assert is_task_due(task, tmp_path) is False


def test_is_task_due_no_previous_run(tmp_path):
    task = {"schedule": "every 1h"}
    assert is_task_due(task, tmp_path) is True


def test_is_task_due_recently_ran(tmp_path):
    task = {"schedule": "every 1h"}
    append_run_log(tmp_path, "TASK_OK", "done")
    assert is_task_due(task, tmp_path, now=datetime.now()) is False


def test_is_task_due_enough_time_passed(tmp_path):
    task = {"schedule": "every 1m"}
    append_run_log(tmp_path, "TASK_OK", "done")
    future = datetime.now() + timedelta(minutes=2)
    assert is_task_due(task, tmp_path, now=future) is True


def test_is_task_due_disabled(tmp_path):
    task = {"schedule": "every 1m", "enabled": "false"}
    assert is_task_due(task, tmp_path) is False


# ── create / list / load / remove ────────────────────────────────

@pytest.fixture
def task_root(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path))
    return tmp_path


def test_create_and_load_task(task_root):
    agent = {"name": "testy", "path": str(task_root / "agents" / "testy")}
    task_file = create_task("Daily Check", agent=agent, schedule="every 1d")
    assert task_file.exists()

    task = load_task(task_file)
    assert task["title"] == "Daily Check"
    assert task["schedule"] == "every 1d"
    assert task["assigned_to"] == "testy"


def test_list_tasks(task_root):
    agent = {"name": "testy", "path": str(task_root / "agents" / "testy")}
    create_task("Task A", agent=agent)
    create_task("Task B", agent=agent)
    tasks = list_tasks(Path(agent["path"]) / "tasks")
    assert len(tasks) == 2


def test_remove_task(task_root):
    agent = {"name": "testy", "path": str(task_root / "agents" / "testy")}
    task_file = create_task("Removable", agent=agent)
    task_dir = task_file.parent
    assert task_dir.exists()
    remove_task(task_dir)
    assert not task_dir.exists()


# ── run log ──────────────────────────────────────────────────────

def test_append_and_last_run(tmp_path):
    assert last_run(tmp_path) is None
    append_run_log(tmp_path, "TASK_OK", 'changes="x" next_steps="y"')
    run = last_run(tmp_path)
    assert run is not None
    assert run["status"] == "TASK_OK"


# ── parse response ───────────────────────────────────────────────

def test_parse_task_response_ok():
    status, msg = parse_task_response('TASK_OK changes="done" next_steps="none"')
    assert status == "TASK_OK"
    assert "changes" in msg


def test_parse_task_response_fail():
    status, msg = parse_task_response('TASK_FAIL reason="broken"')
    assert status == "TASK_FAIL"


def test_parse_task_response_unexpected():
    status, msg = parse_task_response("some random output")
    assert status == "TASK_FAIL"

def test_parse_task_response_rejects_prefix_collisions():
    status, msg = parse_task_response('TASK_OKAY changes="done"')
    assert status == "TASK_FAIL"
    assert "Unexpected output" in msg


def test_parse_task_message_ok():
    result = parse_task_message("TASK_OK", 'changes="updated file" next_steps="review"')
    assert result["status"] == "TASK_OK"
    assert result["changes"] == "updated file"
    assert result["next_steps"] == "review"


def test_parse_task_message_fail():
    result = parse_task_message("TASK_FAIL", 'reason="timeout"')
    assert result["status"] == "TASK_FAIL"
    assert result["reason"] == "timeout"


# ── frontmatter ──────────────────────────────────────────────────

def test_parse_frontmatter():
    content = """---
id: my-task
title: My Task
status: open
assigned_to: "alice"
schedule: "every 1h"
---

# Task body
"""
    data = _parse_frontmatter(content)
    assert data["id"] == "my-task"
    assert data["title"] == "My Task"
    assert data["assigned_to"] == "alice"
    assert data["schedule"] == "every 1h"


def test_parse_frontmatter_no_frontmatter():
    assert _parse_frontmatter("just text") == {}
