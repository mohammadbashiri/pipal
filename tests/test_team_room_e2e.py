import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


PI = shutil.which("pi")
pytestmark = pytest.mark.skipif(PI is None, reason="native pi is not installed")
EXTENSION = Path(__file__).parents[1] / "src" / "pipal" / "extensions" / "team_chat.ts"


def _fake_member_pi(tmp_path: Path) -> Path:
    script = tmp_path / "fake-member-pi"
    script.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

agent = Path(os.environ["PIPAL_AGENT_DIR"]).name
prompt = sys.argv[sys.argv.index("-p") + 1]
if "hang forever" in prompt:
    time.sleep(30)
if agent == "raven":
    if "The agents you addressed replied:" in prompt:
        text = "Ada answered 4; I agree."
    else:
        call_id = "pwd-1"
        args = {"command": "pwd"}
        result = {"content": [{"type": "text", "text": os.getcwd()}], "details": {}}
        print(json.dumps({"type": "tool_execution_start", "toolCallId": call_id, "toolName": "bash", "args": args}), flush=True)
        print(json.dumps({"type": "tool_execution_end", "toolCallId": call_id, "toolName": "bash", "args": args, "result": result, "isError": False}), flush=True)
        text = "@ada, what is 2+2?"
elif agent == "ada":
    text = "4"
else:
    text = "Manager response"
message = {
    "role": "assistant",
    "content": [{"type": "text", "text": text}],
    "usage": {"input": 10, "output": 3, "cost": {"total": 0}},
}
print(json.dumps({"type": "message_end", "message": message}), flush=True)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _runtime(tmp_path: Path, *, timeout: int = 5) -> tuple[dict, Path]:
    working_dir = tmp_path / "project"
    working_dir.mkdir()
    topic_dir = tmp_path / "topic"
    topic_dir.mkdir()
    transcript = topic_dir / "transcript.jsonl"
    transcript.touch()
    fake_pi = _fake_member_pi(tmp_path)
    members = []
    for agent, role in [("sasha", "Manager"), ("ada", "Researcher"), ("raven", "Risk Reviewer")]:
        home = tmp_path / "agents" / agent
        home.mkdir(parents=True)
        prompt = topic_dir / f"{agent}.md"
        prompt.write_text(f"You are @{agent}, {role}.", encoding="utf-8")
        members.append(
            {
                "agent": agent,
                "role": role,
                "agent_path": str(home),
                "provider": "fake",
                "model": "fake",
                "prompt_file": str(prompt),
                "session_file": str(topic_dir / f"{agent}.jsonl"),
            }
        )
    runtime = {
        "schema_version": 1,
        "team": "test-team",
        "owner": "Mo",
        "manager": "sasha",
        "topic": "test",
        "topic_dir": str(topic_dir),
        "transcript_file": str(transcript),
        "working_dir": str(working_dir),
        "native_pi": str(fake_pi),
        "max_rounds": 4,
        "agent_timeout_seconds": timeout,
        "members": members,
    }
    runtime_file = topic_dir / "runtime.json"
    runtime_file.write_text(json.dumps(runtime), encoding="utf-8")
    return runtime, runtime_file


def _run_rpc(runtime_file: Path, prompt: str, done) -> list[dict]:
    env = os.environ.copy()
    env["PIPAL_TEAM_RUNTIME"] = str(runtime_file)
    proc = subprocess.Popen(
        [PI, "--mode", "rpc", "--no-session", "--no-tools", "--extension", str(EXTENSION)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"id": "prompt-1", "type": "prompt", "message": prompt}) + "\n")
        proc.stdin.flush()
        transcript = Path(json.loads(runtime_file.read_text())["transcript_file"])
        deadline = time.time() + 15
        events = []
        while time.time() < deadline:
            if transcript.exists():
                events = [json.loads(line) for line in transcript.read_text().splitlines() if line]
                if done(events):
                    return events
            if proc.poll() is not None:
                stderr = proc.stderr.read() if proc.stderr else ""
                pytest.fail(f"Pi RPC exited early ({proc.returncode}): {stderr}")
            time.sleep(0.05)
        stderr = proc.stderr.read() if proc.stderr and proc.poll() is not None else ""
        pytest.fail(f"Timed out waiting for team room: {stderr}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_pipal_owned_room_routes_mentions_records_tools_and_uses_shared_cwd(tmp_path):
    runtime, runtime_file = _runtime(tmp_path)
    events = _run_rpc(
        runtime_file,
        "@raven ask the researcher for the answer, then assess it",
        lambda items: any(
            item.get("type") == "message"
            and item.get("author", {}).get("name") == "raven"
            and "I agree" in item.get("content", "")
            for item in items
        ),
    )

    messages = [
        (item["author"]["name"], item["content"])
        for item in events
        if item.get("type") == "message"
    ]
    assert messages == [
        ("Mo", "@raven ask the researcher for the answer, then assess it"),
        ("raven", "@ada, what is 2+2?"),
        ("ada", "4"),
        ("raven", "Ada answered 4; I agree."),
    ]
    tool_results = [item for item in events if item.get("type") == "tool_result"]
    assert tool_results[0]["author"]["name"] == "raven"
    assert tool_results[0]["output"] == runtime["working_dir"]


def test_team_room_persists_agent_timeout_as_error(tmp_path):
    _runtime_data, runtime_file = _runtime(tmp_path, timeout=1)
    events = _run_rpc(
        runtime_file,
        "@raven hang forever",
        lambda items: any(item.get("type") == "error" for item in items),
    )
    error = next(item for item in events if item.get("type") == "error")
    assert "timed out after 1s" in error["content"]


def test_team_room_command_cancels_active_agent(tmp_path):
    _runtime_data, runtime_file = _runtime(tmp_path, timeout=20)
    env = os.environ.copy()
    env["PIPAL_TEAM_RUNTIME"] = str(runtime_file)
    proc = subprocess.Popen(
        [PI, "--mode", "rpc", "--no-session", "--no-tools", "--extension", str(EXTENSION)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"id": "work", "type": "prompt", "message": "@raven hang forever"}) + "\n")
        proc.stdin.flush()
        time.sleep(0.3)
        proc.stdin.write(json.dumps({"id": "stop", "type": "prompt", "message": "/team-stop"}) + "\n")
        proc.stdin.flush()
        transcript = Path(json.loads(runtime_file.read_text())["transcript_file"])
        deadline = time.time() + 8
        while time.time() < deadline:
            events = [json.loads(line) for line in transcript.read_text().splitlines() if line]
            warnings = [item for item in events if item.get("type") == "warning"]
            if warnings:
                assert "cancelled" in warnings[-1]["content"].lower()
                return
            time.sleep(0.05)
        pytest.fail("Cancellation was not persisted")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
