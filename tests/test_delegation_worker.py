import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from pipal import delegation_worker
from pipal.delegation_worker import request_cancel, run_job


def _job(tmp_path, *, job_id="dg-test", native_pi=None):
    transcript = tmp_path / "transcript.jsonl"
    transcript.touch()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("delegate prompt", encoding="utf-8")
    return {
        "id": job_id, "status": "queued", "primary": "sasha", "topic": "main",
        "working_dir": str(tmp_path), "native_pi": str(native_pi or tmp_path / "fake-pi"),
        "timeout_seconds": 5, "message": "finish the artifact",
        "session_file": str(tmp_path / "session.jsonl"),
        "delegate": {"agent": "ada", "agent_path": str(tmp_path), "prompt_file": str(prompt), "transcript_file": str(transcript)},
    }


def test_background_delegation_worker_completes_and_persists_result(tmp_path):
    fake_pi = tmp_path / "fake-pi"
    fake_pi.write_text(
        """#!/usr/bin/env python3
import json
args = {"command": "pwd"}
result = {"content": [{"type": "text", "text": "verified"}], "details": {}}
print(json.dumps({"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "bash", "args": args}), flush=True)
print(json.dumps({"type": "tool_execution_end", "toolCallId": "call-1", "toolName": "bash", "args": args, "result": result, "isError": False}), flush=True)
message = {"role": "assistant", "content": [{"type": "text", "text": "completed artifact"}]}
print(json.dumps({"type": "message_end", "message": message}), flush=True)
""",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    transcript = tmp_path / "transcript.jsonl"
    job = _job(tmp_path, native_pi=fake_pi)
    job.update(acceptance_criteria="artifact is complete", reported=False)
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")

    assert run_job(job_file) == 0

    completed = json.loads(job_file.read_text(encoding="utf-8"))
    assert completed["status"] == "completed"
    assert completed["result"] == "completed artifact"
    streamed = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [event["type"] for event in streamed] == [
        "tool_execution_start",
        "tool_execution_end",
        "message_end",
    ]
    events = [json.loads(line) for line in transcript.read_text().splitlines()]
    messages = [(event["author"], event["content"]) for event in events if event["type"] == "message"]
    assert messages == [("sasha", "finish the artifact"), ("ada", "completed artifact")]
    assert next(event for event in events if event["type"] == "tool_result")["output"] == "verified"


def test_worker_does_not_run_an_exclusively_claimed_job(tmp_path):
    fake_pi = tmp_path / "fake-pi"
    fake_pi.write_text("#!/bin/sh\necho should-not-run >&2\nexit 1\n", encoding="utf-8")
    fake_pi.chmod(0o755)
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(_job(tmp_path, native_pi=fake_pi)), encoding="utf-8")
    (tmp_path / "worker-claim.json").write_text(json.dumps({"pid": __import__("os").getpid(), "acquired_at": "2999-01-01T00:00:00Z"}))

    assert run_job(job_file) == 0
    assert json.loads(job_file.read_text())["status"] == "queued"


def test_worker_uses_job_root_as_the_single_durable_completion_source(tmp_path):
    fake_pi = tmp_path / "fake-pi"
    fake_pi.write_text("#!/bin/sh\nprintf '%s\\n' '{\"type\": \"message_end\", \"message\": {\"role\": \"assistant\", \"content\": [{\"type\": \"text\", \"text\": \"done\"}]}}'\n", encoding="utf-8")
    fake_pi.chmod(0o755)
    job = _job(tmp_path, native_pi=fake_pi)
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")

    assert run_job(job_file) == 0
    # A reopen/second poll reads the same terminal job and does not produce a
    # second delivery path (the extension's reported marker owns notification).
    assert run_job(job_file) == 0
    terminal = json.loads(job_file.read_text())
    assert terminal["status"] == "completed"
    assert not list(tmp_path.rglob("completions.jsonl"))


def test_cancellation_cannot_be_overwritten_during_worker_claim(tmp_path, monkeypatch):
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(_job(tmp_path)), encoding="utf-8")
    original_load = delegation_worker._load_job
    second_read = threading.Event()
    continue_read = threading.Event()
    calls = 0

    def controlled_load(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            second_read.set()
            assert continue_read.wait(timeout=2)
        return original_load(path)

    monkeypatch.setattr(delegation_worker, "_load_job", controlled_load)
    claimed = []
    claim_thread = threading.Thread(target=lambda: claimed.append(delegation_worker._claim_job(job_file)))
    claim_thread.start()
    assert second_read.wait(timeout=2)
    cancel_thread = threading.Thread(target=lambda: request_cancel(job_file))
    cancel_thread.start()
    for _ in range(100):
        if (tmp_path / "cancel-requested.json").exists():
            break
        time.sleep(0.01)
    continue_read.set()
    claim_thread.join(timeout=2)
    cancel_thread.join(timeout=2)

    assert claimed == [None]
    assert json.loads(job_file.read_text())["status"] == "cancelled"


def test_cancellation_races_a_live_worker_finalization_without_overwrite(tmp_path):
    fake_pi = tmp_path / "fake-pi"
    fake_pi.write_text("#!/bin/sh\nsleep 0.15\nprintf '%s\\n' '{\"type\": \"message_end\", \"message\": {\"role\": \"assistant\", \"content\": [{\"type\": \"text\", \"text\": \"late done\"}]}}'\n", encoding="utf-8")
    fake_pi.chmod(0o755)
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(_job(tmp_path, native_pi=fake_pi)), encoding="utf-8")
    worker = subprocess.Popen([sys.executable, "-m", "pipal.delegation_worker", str(job_file)])
    for _ in range(100):
        if json.loads(job_file.read_text())["status"] == "running":
            break
        time.sleep(0.01)
    assert json.loads(job_file.read_text())["status"] == "running"
    # Model the extension's cross-process cancellation marker racing normal
    # worker finalization; the worker must not overwrite it with completion.
    request_cancel(job_file)
    assert worker.wait(timeout=3) == 0
    assert json.loads(job_file.read_text())["status"] == "cancelled"
