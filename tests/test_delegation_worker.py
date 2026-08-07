import json
from pathlib import Path

from pipal.delegation_worker import run_job


def test_background_delegation_worker_completes_and_persists_result(tmp_path):
    fake_pi = tmp_path / "fake-pi"
    fake_pi.write_text(
        """#!/usr/bin/env python3
import json
message = {"role": "assistant", "content": [{"type": "text", "text": "completed artifact"}]}
print(json.dumps({"type": "message_end", "message": message}))
""",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    transcript = tmp_path / "transcript.jsonl"
    transcript.touch()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("delegate prompt", encoding="utf-8")
    job = {
        "id": "dg-test",
        "status": "queued",
        "primary": "sasha",
        "topic": "main",
        "working_dir": str(tmp_path),
        "native_pi": str(fake_pi),
        "timeout_seconds": 5,
        "message": "finish the artifact",
        "acceptance_criteria": "artifact is complete",
        "session_file": str(tmp_path / "session.jsonl"),
        "delegate": {
            "agent": "ada",
            "agent_path": str(tmp_path),
            "prompt_file": str(prompt),
            "transcript_file": str(transcript),
        },
        "reported": False,
    }
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")

    assert run_job(job_file) == 0

    completed = json.loads(job_file.read_text(encoding="utf-8"))
    assert completed["status"] == "completed"
    assert completed["result"] == "completed artifact"
    events = [json.loads(line) for line in transcript.read_text().splitlines()]
    assert [(event["author"], event["content"]) for event in events] == [
        ("sasha", "finish the artifact"),
        ("ada", "completed artifact"),
    ]
