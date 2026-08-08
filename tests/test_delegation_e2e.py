import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


PI = shutil.which("pi")
pytestmark = pytest.mark.skipif(PI is None, reason="native pi is not installed")
EXTENSION = Path(__file__).parents[1] / "src" / "pipal" / "extensions" / "delegation.ts"


def test_background_completion_is_passive_and_does_not_trigger_agent_turn():
    source = EXTENSION.read_text(encoding="utf-8")
    completion_path = source.split("const reportFinishedJobs", 1)[1].split("pi.registerTool", 1)[0]
    assert "notify?." in completion_path
    assert "triggerTurn" not in completion_path
    assert "pipal-delegation-complete" not in source


def test_namespaced_direct_agent_message_uses_persistent_delegate(tmp_path):
    working_dir = tmp_path / "project"
    working_dir.mkdir()
    delegate_home = tmp_path / "agents" / "ada"
    delegate_home.mkdir(parents=True)
    thread = tmp_path / "delegations" / "ada"
    thread.mkdir(parents=True)
    transcript = thread / "transcript.jsonl"
    transcript.touch()
    prompt_file = thread / "prompt.md"
    prompt_file.write_text("You are Ada.", encoding="utf-8")

    fake_pi = tmp_path / "fake-pi"
    fake_pi.write_text(
        """#!/usr/bin/env python3
import json
import os
call = "pwd-1"
args = {"command": "pwd"}
result = {"content": [{"type": "text", "text": os.getcwd()}], "details": {}}
print(json.dumps({"type": "tool_execution_start", "toolCallId": call, "toolName": "bash", "args": args}), flush=True)
print(json.dumps({"type": "tool_execution_end", "toolCallId": call, "toolName": "bash", "args": args, "result": result, "isError": False}), flush=True)
message = {"role": "assistant", "content": [{"type": "text", "text": os.getcwd()}], "usage": {"input": 4, "output": 2, "cost": {"total": 0}}}
print(json.dumps({"type": "message_end", "message": message}), flush=True)
""",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)

    runtime = {
        "schema_version": 1,
        "primary": "sasha",
        "primary_path": str(tmp_path / "agents" / "sasha"),
        "topic": "main",
        "working_dir": str(working_dir),
        "native_pi": str(fake_pi),
        "agent_timeout_seconds": 5,
        "max_turns": 4,
        "delegates": [
            {
                "agent": "ada",
                "role": "Pipal agent",
                "agent_path": str(delegate_home),
                "provider": "fake",
                "model": "fake",
                "prompt_file": str(prompt_file),
                "session_file": str(thread / "session.jsonl"),
                "transcript_file": str(transcript),
            }
        ],
    }
    runtime_file = tmp_path / "runtime.json"
    runtime_file.write_text(json.dumps(runtime), encoding="utf-8")
    env = os.environ.copy()
    env["PIPAL_DELEGATION_RUNTIME"] = str(runtime_file)
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
        proc.stdin.write(json.dumps({"id": "direct", "type": "prompt", "message": "@agent:ada report pwd"}) + "\n")
        proc.stdin.flush()
        deadline = time.time() + 10
        events = []
        while time.time() < deadline:
            events = [json.loads(line) for line in transcript.read_text().splitlines() if line]
            if any(item.get("type") == "message" and item.get("author") == "ada" for item in events):
                break
            if proc.poll() is not None:
                pytest.fail(proc.stderr.read() if proc.stderr else "Pi RPC exited")
            time.sleep(0.05)
        else:
            pytest.fail("Timed out waiting for direct delegate response")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    messages = [(event["author"], event["content"]) for event in events if event.get("type") == "message"]
    assert messages == [("owner", "@agent:ada report pwd"), ("ada", str(working_dir))]
    tool_result = next(event for event in events if event.get("type") == "tool_result")
    assert tool_result["output"] == str(working_dir)
