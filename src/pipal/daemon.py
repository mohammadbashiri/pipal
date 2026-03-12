"""Daemon process for pipal heartbeat.

Runs as a detached background process.  Wakes up on interval,
invokes the agent non-interactively to run its heartbeat checklist,
then goes back to sleep.
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .tasks import list_tasks, load_task, is_task_due, schedule_seconds


# ── paths ────────────────────────────────────────────────────────

def _pid_path(agent_path: str) -> Path:
    return Path(agent_path) / "daemon.pid"


def _meta_path(agent_path: str) -> Path:
    return Path(agent_path) / "daemon.json"


def _log_path(agent_path: str) -> Path:
    return Path(agent_path) / "daemon.log"


# ── helpers ──────────────────────────────────────────────────────

def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _find_project_root() -> Path:
    d = Path(__file__).resolve().parent
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    raise FileNotFoundError("Could not find pyproject.toml")


def _routine_files(agent_path: str) -> list[Path]:
    routines = Path(agent_path) / "routines"
    if not routines.exists():
        return []
    return sorted(p for p in routines.glob("*.md") if p.is_file())


def _daemon_guard(agent_path: str, current_pid: int) -> tuple[bool, str]:
    """Return (ok, reason). Daemon should stop when guard fails."""
    agent_dir = Path(agent_path)
    if not agent_dir.exists():
        return False, "agent path no longer exists"

    pid_file = _pid_path(agent_path)
    if not pid_file.exists():
        return False, "pid file missing"

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return False, "pid file is invalid"

    if pid != current_pid:
        return False, f"pid mismatch (expected {current_pid}, found {pid})"

    return True, ""


def parse_interval(s: str) -> int:
    """Parse '30m', '1h', '2h30m', '90s' into seconds."""
    s = s.strip().lower()
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", s)
    if not m or not any(m.groups()):
        raise ValueError(f"Invalid interval: {s}. Use e.g. 30m, 1h, 2h30m")
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    total = hours * 3600 + minutes * 60 + seconds
    if total == 0:
        raise ValueError("Interval must be > 0")
    return total


def format_interval(seconds: int) -> str:
    """Format seconds into human-readable like '30m', '1h 30m'."""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s:
        parts.append(f"{s}s")
    return " ".join(parts) or "0s"


def format_uptime(started_at: str) -> str:
    """Format elapsed time since started_at ISO string."""
    start = datetime.fromisoformat(started_at)
    delta = datetime.now() - start
    total = int(delta.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


# ── daemon loop (runs in the background process) ─────────────────

def _run_loop(
    agent_name: str,
    agent_path: str,
    interval: int,
    uv_bin: str,
    project_root: str,
):
    """Infinite heartbeat loop.  Runs inside the detached process."""

    # Write PID
    _pid_path(agent_path).write_text(str(os.getpid()))

    # Write metadata
    meta = {
        "agent_name": agent_name,
        "interval_seconds": interval,
        "started_at": datetime.now().isoformat(),
        "last_heartbeat": None,
    }
    _meta_path(agent_path).write_text(json.dumps(meta, indent=2) + "\n")

    # Graceful shutdown
    def _handle_stop(signum, frame):
        now = datetime.now().isoformat()
        print(f"[{now}] Daemon stopped (signal {signum})", flush=True)
        _pid_path(agent_path).unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    print(f"[{datetime.now().isoformat()}] Daemon started for {agent_name} "
          f"(every {format_interval(interval)})", flush=True)

    while True:
        try:
            ok, reason = _daemon_guard(agent_path, os.getpid())
            if not ok:
                print(
                    f"[{datetime.now().isoformat()}] Daemon stopping: {reason}",
                    flush=True,
                )
                _meta_path(agent_path).unlink(missing_ok=True)
                break

            now = datetime.now().isoformat()
            print(f"\n[{now}] Heartbeat tick", flush=True)
            tasks_root = Path(agent_path) / "tasks"
            tasks = list_tasks(tasks_root)
            if not tasks:
                print("HEARTBEAT_OK (no tasks found)", flush=True)
            else:
                due_any = False
                for task_id, task_file in tasks:
                    task = load_task(task_file)
                    if not is_task_due(task, task_file.parent, now=datetime.fromisoformat(now)):
                        continue
                    due_any = True
                    every = schedule_seconds(task.get("schedule"))
                    every_label = format_interval(every) if every else "unknown"
                    print(f"Running task: {task_id} (every {every_label})", flush=True)
                    try:
                        result = subprocess.run(
                            [
                                uv_bin, "run", "pipal",
                                "task", "run",
                                task_id,
                                "--agent", agent_name,
                            ],
                            cwd=project_root,
                            capture_output=True,
                            text=True,
                            timeout=300,  # 5 min max per task
                        )

                        output = (result.stdout or "").strip()
                        if output:
                            print(output, flush=True)
                        else:
                            print("TASK_FAIL No output from task run", flush=True)

                        if result.stderr:
                            print(result.stderr, flush=True)
                    except subprocess.TimeoutExpired:
                        print(
                            f"TASK_FAIL {task_id} timed out after 300s",
                            flush=True,
                        )

                if not due_any:
                    print("HEARTBEAT_OK (no due tasks)", flush=True)

            # Update last heartbeat
            meta["last_heartbeat"] = now
            _meta_path(agent_path).write_text(
                json.dumps(meta, indent=2) + "\n"
            )

        except subprocess.TimeoutExpired:
            print(f"[{datetime.now().isoformat()}] Heartbeat timed out", flush=True)
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error: {e}", flush=True)

        time.sleep(interval)


# ── public API (called from cli.py) ─────────────────────────────

def start_daemon(agent_name: str, agent_path: str, interval: int):
    """Launch the daemon as a detached background process."""
    pid_file = _pid_path(agent_path)

    # Check if already running
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            if _is_running(pid):
                raise RuntimeError(f"Daemon already running (PID {pid})")
        except ValueError:
            pass
        pid_file.unlink(missing_ok=True)

    uv_bin = shutil.which("uv")
    if not uv_bin:
        raise FileNotFoundError("Could not find uv. Is it installed?")

    project_root = _find_project_root()
    log_file = _log_path(agent_path)

    log_fd = open(log_file, "a")

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "pipal.daemon",
            "--agent-name", agent_name,
            "--agent-path", agent_path,
            "--interval", str(interval),
            "--uv-bin", uv_bin,
            "--project-root", str(project_root),
        ],
        start_new_session=True,
        stdout=log_fd,
        stderr=log_fd,
        stdin=subprocess.DEVNULL,
    )

    # Give it a moment to write PID
    time.sleep(0.5)

    return proc.pid


def stop_daemon(agent_path: str) -> bool:
    """Stop the daemon.  Returns True if it was running."""
    pid_file = _pid_path(agent_path)
    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        return False

    if not _is_running(pid):
        pid_file.unlink(missing_ok=True)
        return False

    os.kill(pid, signal.SIGTERM)
    pid_file.unlink(missing_ok=True)
    _meta_path(agent_path).unlink(missing_ok=True)
    return True


def daemon_status(agent_path: str) -> dict | None:
    """Return daemon status dict, or None if not running."""
    pid_file = _pid_path(agent_path)
    meta_file = _meta_path(agent_path)

    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return None

    if not _is_running(pid):
        # Stale
        pid_file.unlink(missing_ok=True)
        return None

    meta = {}
    if meta_file.exists():
        with meta_file.open() as f:
            meta = json.load(f)

    return {
        "pid": pid,
        "interval": meta.get("interval_seconds"),
        "started_at": meta.get("started_at"),
        "last_heartbeat": meta.get("last_heartbeat"),
        "log": str(_log_path(agent_path)),
    }


def daemon_logs(agent_path: str, lines: int = 50) -> str:
    """Return the last N lines of the daemon log."""
    log = _log_path(agent_path)
    if not log.exists():
        return ""
    all_lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(all_lines[-lines:])


# ── entry point (used by the background process) ────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--agent-name", required=True)
    p.add_argument("--agent-path", required=True)
    p.add_argument("--interval", type=int, required=True)
    p.add_argument("--uv-bin", required=True)
    p.add_argument("--project-root", required=True)
    args = p.parse_args()

    _run_loop(
        agent_name=args.agent_name,
        agent_path=args.agent_path,
        interval=args.interval,
        uv_bin=args.uv_bin,
        project_root=args.project_root,
    )
