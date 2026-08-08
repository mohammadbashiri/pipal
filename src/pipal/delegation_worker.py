from __future__ import annotations

import argparse
import fcntl
import json
import os
import selectors
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLAIM_LEASE_SECONDS = 60 * 60
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_job(path: Path, job: dict[str, Any]) -> None:
    """Atomically replace a job file; readers never observe a partial JSON document."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load_job(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pid_alive(pid: object) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, OSError):
        return False


def _claim_job(job_file: Path) -> dict[str, Any] | None:
    """Acquire one worker lease without racing terminal cancellation."""
    claim = job_file.parent / "worker-claim.json"
    cancel_marker = job_file.parent / "cancel-requested.json"
    lock_file = job_file.parent / ".finalize.lock"
    lock_file.touch(exist_ok=True)
    for _ in range(3):
        retry = False
        with lock_file.open("r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                job = _load_job(job_file)
                if cancel_marker.exists():
                    if job.get("status") not in TERMINAL_STATUSES:
                        job.update(status="cancelled", finished_at=job.get("finished_at") or _now(), error="Cancelled by owner")
                        _write_job(job_file, job)
                    return None
                if job.get("status") in TERMINAL_STATUSES:
                    return None
                try:
                    fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    try:
                        existing = json.loads(claim.read_text(encoding="utf-8"))
                        acquired = datetime.fromisoformat(str(existing.get("acquired_at", "")).replace("Z", "+00:00"))
                        stale = (datetime.now(timezone.utc) - acquired).total_seconds() > CLAIM_LEASE_SECONDS
                    except (OSError, ValueError, json.JSONDecodeError):
                        existing, stale = {}, True
                    if stale or not _pid_alive(existing.get("pid")):
                        claim.unlink(missing_ok=True)
                        retry = True
                    else:
                        return None
                else:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump({"pid": os.getpid(), "acquired_at": _now()}, handle)
                        handle.write("\n")
                    # The marker is written before request_cancel waits for this
                    # lock, so this recheck closes the final interleaving window.
                    job = _load_job(job_file)
                    if cancel_marker.exists():
                        job.update(status="cancelled", finished_at=job.get("finished_at") or _now(), error="Cancelled by owner")
                        _write_job(job_file, job)
                        claim.unlink(missing_ok=True)
                        return None
                    if job.get("status") in TERMINAL_STATUSES:
                        claim.unlink(missing_ok=True)
                        return None
                    job.update(status="running", started_at=job.get("started_at") or _now(), pid=os.getpid())
                    _write_job(job_file, job)
                    return job
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        if retry:
            continue
    return None


def _release_claim(job_file: Path) -> None:
    claim = job_file.parent / "worker-claim.json"
    try:
        data = json.loads(claim.read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            claim.unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError):
        pass


def _append_thread(job: dict[str, Any], event: dict[str, Any]) -> None:
    transcript = Path(job["delegate"]["transcript_file"])
    transcript.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "timestamp": _now(), **event}
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _append_job_event(job_file: Path, event: dict[str, Any]) -> None:
    path = job_file.parent / "events.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": _now(), **event}, ensure_ascii=False) + "\n")


def _lineage(job: dict[str, Any]) -> dict[str, Any]:
    return {"parent_job_id": job["parent_job_id"]} if job.get("parent_job_id") else {}


def _finalize(job_file: Path, status: str, **values: Any) -> dict[str, Any]:
    """Atomically choose one terminal outcome; cancellation wins if it locks first."""
    lock_file = job_file.parent / ".finalize.lock"
    lock_file.touch(exist_ok=True)
    with lock_file.open("r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            current = _load_job(job_file)
            cancel_requested = (job_file.parent / "cancel-requested.json").exists()
            if cancel_requested and status != "cancelled":
                status = "cancelled"
                values = {"error": "Cancelled by owner"}
            if current.get("status") == "cancelled" and status != "cancelled":
                return current
            if current.get("status") in TERMINAL_STATUSES and current.get("status") != status:
                return current
            current.update(status=status, finished_at=current.get("finished_at") or _now(), **values)
            _write_job(job_file, current)
            return current
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def request_cancel(job_file: Path) -> dict[str, Any]:
    """Persist a cancellation request and choose the terminal outcome under lock."""
    marker = job_file.parent / "cancel-requested.json"
    marker.write_text(json.dumps({"requested_at": _now()}) + "\n", encoding="utf-8")
    return _finalize(job_file, "cancelled", error="Cancelled by owner")


def _text(message: dict[str, Any]) -> str:
    if message.get("role") != "assistant":
        return ""
    return "\n".join(part.get("text", "") for part in message.get("content", []) if part.get("type") == "text").strip()


def run_job(job_file: Path) -> int:
    job_file = job_file.resolve()
    job = _claim_job(job_file)
    if job is None:
        return 0
    active_process: list[subprocess.Popen[str] | None] = [None]

    def cancel(_signum: int, _frame: object) -> None:
        if active_process[0] and active_process[0].poll() is None:
            active_process[0].terminate()
            try:
                active_process[0].wait(timeout=2)
            except subprocess.TimeoutExpired:
                active_process[0].kill()
        _finalize(job_file, "cancelled", error="Cancelled by owner")
        _release_claim(job_file)
        raise SystemExit(130)

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    delegate = job["delegate"]
    prompt_parts = [f"Background Pipal delegation from @agent:{job['primary']} in topic {job['topic']}.", f"Shared working directory: {job['working_dir']}", "", job["message"]]
    if job.get("acceptance_criteria"):
        prompt_parts += ["", "Acceptance criteria:", job["acceptance_criteria"]]
    prompt_parts += ["", "Complete the work independently and return concrete results, artifacts, verification, or a precise blocker."]
    args = [job["native_pi"], "--mode", "json", "--session", job["session_file"], "--append-system-prompt", delegate["prompt_file"]]
    if delegate.get("provider"):
        args += ["--provider", delegate["provider"]]
    if delegate.get("model"):
        args += ["--model", delegate["model"]]
    args += ["-p", "\n".join(prompt_parts)]
    env = os.environ.copy()
    env.update(PIPAL_AGENT_DIR=delegate["agent_path"], PIPAL_TOPIC=job["topic"], PIPAL_DISABLE_AUTOGREET="1")
    final_text = ""
    lineage = _lineage(job)
    _append_thread(job, {"type": "message", "author": job["primary"], "content": job["message"], "acceptance_criteria": job.get("acceptance_criteria"), "background_job": job["id"], "delegation_id": job.get("delegation_id", job["id"]), "team": job.get("team"), **lineage})
    try:
        proc = subprocess.Popen(args, cwd=job["working_dir"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        active_process[0] = proc
        selector = selectors.DefaultSelector()
        assert proc.stdout is not None
        selector.register(proc.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + int(job.get("timeout_seconds", 300))
        diagnostic: list[str] = []
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                proc.terminate()
                try: proc.wait(timeout=2)
                except subprocess.TimeoutExpired: proc.kill()
                raise TimeoutError
            for key, _ in selector.select(timeout=0.2):
                line = key.fileobj.readline()
                if not line: continue
                try: event = json.loads(line)
                except json.JSONDecodeError:
                    diagnostic.append(line.strip()); continue
                _append_job_event(job_file, {**event, **lineage})
                if event.get("type") == "tool_execution_start":
                    _append_thread(job, {"type": "tool_call", "author": delegate["agent"], "tool": event.get("toolName"), "args": event.get("args", {}), "tool_call_id": event.get("toolCallId"), "delegation_id": job.get("delegation_id", job["id"]), "background_job": job["id"], **lineage})
                elif event.get("type") == "tool_execution_end":
                    result = event.get("result", {})
                    output = "\n".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")
                    _append_thread(job, {"type": "tool_result", "author": delegate["agent"], "tool": event.get("toolName"), "output": output, "is_error": bool(event.get("isError")), "tool_call_id": event.get("toolCallId"), "delegation_id": job.get("delegation_id", job["id"]), "background_job": job["id"], **lineage})
                elif event.get("type") == "message_end":
                    final_text = _text(event.get("message", {})) or final_text
        for line in proc.stdout:
            try:
                event = json.loads(line); _append_job_event(job_file, {**event, **lineage})
                if event.get("type") == "message_end": final_text = _text(event.get("message", {})) or final_text
            except json.JSONDecodeError: diagnostic.append(line.strip())
        if proc.returncode != 0:
            raise RuntimeError("\n".join(filter(None, diagnostic[-3:])) or f"delegate exited with code {proc.returncode}")
        completed = _finalize(job_file, "completed", result=final_text or "(no response)")
        if completed.get("status") == "completed":
            _append_thread(completed, {"type": "message", "author": delegate["agent"], "content": completed["result"], "background_job": completed["id"], "delegation_id": completed.get("delegation_id", completed["id"]), "team": completed.get("team"), **_lineage(completed)})
        return 0
    except TimeoutError:
        _finalize(job_file, "failed", error=f"Timed out after {job.get('timeout_seconds', 300)}s")
    except Exception as exc:
        _finalize(job_file, "failed", error=str(exc))
    finally:
        _release_claim(job_file)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cancel", action="store_true")
    parser.add_argument("job_file")
    args = parser.parse_args(argv)
    job_file = Path(args.job_file).resolve()
    if args.cancel:
        request_cancel(job_file)
        return 0
    return run_job(job_file)


if __name__ == "__main__":
    raise SystemExit(main())
