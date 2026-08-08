from __future__ import annotations

import argparse
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_job(path: Path, job: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_thread(job: dict, event: dict) -> None:
    transcript = Path(job["delegate"]["transcript_file"])
    payload = {
        "schema_version": 1,
        "timestamp": _now(),
        **event,
    }
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _append_job_event(job_file: Path, event: dict) -> None:
    path = job_file.parent / "events.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": _now(), **event}, ensure_ascii=False) + "\n")


def _text(message: dict) -> str:
    if message.get("role") != "assistant":
        return ""
    return "\n".join(
        part.get("text", "")
        for part in message.get("content", [])
        if part.get("type") == "text"
    ).strip()


def run_job(job_file: Path) -> int:
    job = json.loads(job_file.read_text(encoding="utf-8"))
    if job.get("status") == "cancelled":
        return 130
    job.update(status="running", started_at=_now(), pid=os.getpid())
    _write_job(job_file, job)
    active_process: list[subprocess.Popen | None] = [None]

    def cancel(_signum, _frame):
        if active_process[0] and active_process[0].poll() is None:
            active_process[0].terminate()
            try:
                active_process[0].wait(timeout=2)
            except subprocess.TimeoutExpired:
                active_process[0].kill()
        current = json.loads(job_file.read_text(encoding="utf-8"))
        current.update(status="cancelled", finished_at=_now(), error="Cancelled by owner")
        _write_job(job_file, current)
        raise SystemExit(130)

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)

    delegate = job["delegate"]
    task = [
        f"Background Pipal delegation from @agent:{job['primary']} in topic {job['topic']}.",
        f"Shared working directory: {job['working_dir']}",
        "",
        job["message"],
    ]
    if job.get("acceptance_criteria"):
        task += ["", "Acceptance criteria:", job["acceptance_criteria"]]
    task += ["", "Complete the work independently and return concrete results, artifacts, verification, or a precise blocker."]

    args = [
        job["native_pi"],
        "--mode", "json",
        "--session", job["session_file"],
        "--append-system-prompt", delegate["prompt_file"],
    ]
    if delegate.get("provider"):
        args += ["--provider", delegate["provider"]]
    if delegate.get("model"):
        args += ["--model", delegate["model"]]
    args += ["-p", "\n".join(task)]
    env = os.environ.copy()
    env.update(
        PIPAL_AGENT_DIR=delegate["agent_path"],
        PIPAL_TOPIC=job["topic"],
        PIPAL_DISABLE_AUTOGREET="1",
    )

    final_text = ""
    _append_thread(job, {
        "type": "message",
        "author": job["primary"],
        "content": job["message"],
        "acceptance_criteria": job.get("acceptance_criteria"),
        "background_job": job["id"],
        "delegation_id": job.get("delegation_id", job["id"]),
        "team": job.get("team"),
    })
    try:
        proc = subprocess.Popen(
            args,
            cwd=job["working_dir"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        active_process[0] = proc
        selector = selectors.DefaultSelector()
        assert proc.stdout is not None
        selector.register(proc.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + int(job.get("timeout_seconds", 300))
        diagnostic: list[str] = []
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise TimeoutError
            for key, _ in selector.select(timeout=0.2):
                line = key.fileobj.readline()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    diagnostic.append(line.strip())
                    continue
                _append_job_event(job_file, event)
                event_type = event.get("type")
                if event_type == "tool_execution_start":
                    _append_thread(job, {
                        "type": "tool_call", "author": delegate["agent"],
                        "tool": event.get("toolName"), "args": event.get("args", {}),
                        "tool_call_id": event.get("toolCallId"),
                        "delegation_id": job.get("delegation_id", job["id"]),
                        "background_job": job["id"],
                    })
                elif event_type == "tool_execution_end":
                    result = event.get("result", {})
                    output = "\n".join(
                        part.get("text", "") for part in result.get("content", [])
                        if part.get("type") == "text"
                    )
                    _append_thread(job, {
                        "type": "tool_result", "author": delegate["agent"],
                        "tool": event.get("toolName"), "output": output,
                        "is_error": bool(event.get("isError")),
                        "tool_call_id": event.get("toolCallId"),
                        "delegation_id": job.get("delegation_id", job["id"]),
                        "background_job": job["id"],
                    })
                elif event_type == "message_end":
                    value = _text(event.get("message", {}))
                    if value:
                        final_text = value
        # Drain events written just before process exit.
        for line in proc.stdout:
            try:
                event = json.loads(line)
                _append_job_event(job_file, event)
                if event.get("type") == "message_end":
                    final_text = _text(event.get("message", {})) or final_text
            except json.JSONDecodeError:
                diagnostic.append(line.strip())
        if proc.returncode != 0:
            raise RuntimeError("\n".join(filter(None, diagnostic[-3:])) or f"delegate exited with code {proc.returncode}")
        job.update(status="completed", result=final_text or "(no response)", finished_at=_now())
        _append_thread(job, {
            "type": "message",
            "author": delegate["agent"],
            "content": job["result"],
            "background_job": job["id"],
            "delegation_id": job.get("delegation_id", job["id"]),
            "team": job.get("team"),
        })
        _write_job(job_file, job)
        return 0
    except TimeoutError:
        job.update(status="failed", error=f"Timed out after {job.get('timeout_seconds', 300)}s", finished_at=_now())
    except Exception as exc:
        job.update(status="failed", error=str(exc), finished_at=_now())
    _write_job(job_file, job)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_file")
    args = parser.parse_args(argv)
    return run_job(Path(args.job_file).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
