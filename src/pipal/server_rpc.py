from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator

from .server_config import ServerSettings
from .server_context import load_persona, load_summary, new_session_file, read_agent_type
from .server_models import RpcEvent


class PiRpcClient:
    def __init__(
        self,
        settings: ServerSettings,
        agent_dir: Path,
        session_name: str = "main",
        session_file: Path | None = None,
        llm_config: dict[str, Any] | None = None,
        read_only_tools: bool = False,
    ):
        self.settings = settings
        self.agent_dir = agent_dir
        self.session_name = session_name
        self.session_file = session_file
        self.llm_config = llm_config or {}
        self.read_only_tools = read_only_tools
        self.proc: asyncio.subprocess.Process | None = None
        self._queue: asyncio.Queue[RpcEvent] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self.lock = asyncio.Lock()

    def _build_cmd(self) -> list[str]:
        system_prompt = load_persona(self.agent_dir)
        summary = load_summary(self.agent_dir, self.session_name)
        if summary:
            summary_block = (
                "Rolling summary (supplemental; core files are authoritative if conflicts):\n"
                f"{summary}"
            )
            system_prompt = f"{system_prompt}\n\n---\n\n{summary_block}" if system_prompt else summary_block

        session_file = self.session_file or new_session_file(self.agent_dir, self.session_name)
        cmd = [self.settings.pi_bin, "--mode", "rpc", "--session", str(session_file)]

        provider = self.llm_config.get("provider")
        model = self.llm_config.get("model")
        if provider:
            cmd += ["--provider", provider]
        if model:
            cmd += ["--model", model]

        agent_type = read_agent_type(self.agent_dir)
        if agent_type == "kbchat" or self.read_only_tools:
            cmd += ["--tools", "read,grep,find,ls"]

        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]

        ext_dir = self.settings.pipal_extensions_dir
        if ext_dir:
            greet_ext = "kbchat_greet.ts" if agent_type == "kbchat" else "auto_greet.ts"
            for ext in ("rolling_summary.ts", greet_ext):
                ext_path = ext_dir / ext
                if ext_path.exists():
                    cmd += ["--extension", str(ext_path)]

        return cmd

    async def start(self) -> None:
        if self.proc:
            return
        cmd = self._build_cmd()
        env = {**dict(os.environ), "PIPAL_AGENT_DIR": str(self.agent_dir)}
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())

    async def close(self) -> None:
        if self.proc and self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        if self.proc:
            self.proc.terminate()
        if self._reader_task:
            self._reader_task.cancel()

    async def send(self, payload: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("RPC process not started")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        await self.proc.stdin.drain()

    async def events(self) -> AsyncIterator[RpcEvent]:
        while True:
            event = await self._queue.get()
            yield event

    async def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        buffer = b""
        while True:
            chunk = await self.proc.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line:
                    continue
                if line.endswith(b"\r"):
                    line = line[:-1]
                try:
                    data = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                await self._queue.put(RpcEvent(type=data.get("type", ""), data=data))

        if buffer.strip():
            try:
                data = json.loads(buffer.decode("utf-8"))
                await self._queue.put(RpcEvent(type=data.get("type", ""), data=data))
            except Exception:
                pass
