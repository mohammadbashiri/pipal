from __future__ import annotations

import asyncio
import json
import uuid
import ipaddress
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .llm_config import load_llm_config
from .registry import list_agents as registry_list_agents, get_agent
from .server_config import ServerSettings
from .server_context import (
    ensure_session_meta,
    update_session_meta,
    update_session_title_from_prompt,
)
from .server_models import AgentInfo, SessionInfo, SessionFileInfo
from .server_rpc import PiRpcClient


def create_app(
    *,
    agent_scope: str | None = None,
    session_scope: str | None = None,
    session_file_scope: str | None = None,
    read_only: bool = False,
    read_only_tools: bool = False,
) -> FastAPI:
    settings = ServerSettings.load()
    app = FastAPI(title="pipal server", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_auth(token: Optional[str]) -> None:
        expected = settings.auth_token
        if expected and token != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")

    def _list_agents() -> list[AgentInfo]:
        if agent_scope:
            agent = get_agent(agent_scope)
            if not agent:
                return []
            return [AgentInfo(name=agent["name"], path=Path(agent["path"]))]
        agents = registry_list_agents()
        return [AgentInfo(name=name, path=Path(path)) for name, path in agents.items()]

    def _get_agent(agent_name: str) -> AgentInfo | None:
        if agent_scope and agent_name != agent_scope:
            return None
        agent = get_agent(agent_name)
        if not agent:
            return None
        return AgentInfo(name=agent["name"], path=Path(agent["path"]))

    def _list_sessions(agent: AgentInfo) -> list[dict]:
        sessions_dir = agent.path / "sessions"
        if not sessions_dir.exists():
            return []
        sessions: list[dict] = []
        for path in sessions_dir.iterdir():
            if path.is_dir():
                if session_scope and path.name != session_scope:
                    continue
                meta = ensure_session_meta(path)
                sessions.append({"name": path.name, "path": path, **meta})
        return sorted(sessions, key=lambda s: s.get("updated_at", ""), reverse=True)

    def _list_session_files(agent: AgentInfo, session_name: str) -> list[SessionFileInfo]:
        session_dir = agent.path / "sessions" / session_name
        if not session_dir.exists():
            return []
        files = sorted(session_dir.glob("*.jsonl"), reverse=True)
        if session_file_scope:
            files = [p for p in files if p.name == session_file_scope]
        return [SessionFileInfo(name=p.name, path=p) for p in files]

    def _extract_text(message: dict) -> str:
        content = message.get("content") or []
        parts = []
        for item in content:
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts).strip()

    def _load_history_from_file(path: Path) -> list[dict]:
        history: list[dict] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return history
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "message":
                continue
            msg = entry.get("message") or {}
            role = msg.get("role")
            if role not in {"user", "assistant"}:
                continue
            text = _extract_text(msg)
            if not text:
                continue
            history.append({"role": role, "content": text})
        return history

    def _load_session_history(agent: AgentInfo, session_name: str) -> list[dict]:
        session_dir = agent.path / "sessions" / session_name
        if not session_dir.exists():
            return []
        files = sorted(p for p in session_dir.glob("*.jsonl"))
        history: list[dict] = []
        for file in files:
            history.extend(_load_history_from_file(file))
        return history

    def _load_session_file_history(agent: AgentInfo, session_name: str, filename: str) -> list[dict]:
        session_dir = agent.path / "sessions" / session_name
        if not session_dir.exists():
            return []
        target = session_dir / filename
        if not target.exists():
            return []
        return _load_history_from_file(target)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path.startswith("/health"):
            return await call_next(request)
        token = request.headers.get("Authorization")
        token = token.split("Bearer ")[-1] if token else None
        try:
            require_auth(token)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/agents")
    async def get_agents():
        return [{"name": a.name} for a in _list_agents()]

    @app.get("/agents/{agent_name}/sessions")
    async def get_sessions(agent_name: str):
        agent = _get_agent(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        sessions = _list_sessions(agent)
        return [
            {
                "name": s["name"],
                "title": s.get("title"),
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
            }
            for s in sessions
        ]

    @app.get("/agents/{agent_name}/sessions/{session_name}/history")
    async def get_session_history(agent_name: str, session_name: str):
        agent = _get_agent(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if session_scope and session_name != session_scope:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"messages": _load_session_history(agent, session_name)}

    @app.get("/agents/{agent_name}/sessions/{session_name}/files")
    async def get_session_files(agent_name: str, session_name: str):
        agent = _get_agent(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if session_scope and session_name != session_scope:
            raise HTTPException(status_code=404, detail="Session not found")
        return [{"name": f.name} for f in _list_session_files(agent, session_name)]

    @app.get("/agents/{agent_name}/sessions/{session_name}/files/{file_name}/history")
    async def get_session_file_history(agent_name: str, session_name: str, file_name: str):
        agent = _get_agent(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if session_scope and session_name != session_scope:
            raise HTTPException(status_code=404, detail="Session not found")
        if session_file_scope and file_name != session_file_scope:
            raise HTTPException(status_code=404, detail="File not found")
        return {"messages": _load_session_file_history(agent, session_name, file_name)}

    @app.post("/agents/{agent_name}/sessions")
    async def create_session(agent_name: str):
        if read_only:
            raise HTTPException(status_code=403, detail="Read-only mode")
        agent = _get_agent(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        session_name = uuid.uuid4().hex[:8]
        session_dir = agent.path / "sessions" / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        ensure_session_meta(session_dir)
        return {"name": session_name}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        token = websocket.headers.get("Authorization")
        token = token.split("Bearer ")[-1] if token else None
        query_token = websocket.query_params.get("token") if hasattr(websocket, "query_params") else None
        effective_token = token or query_token
        if settings.auth_token and effective_token != settings.auth_token:
            await websocket.close(code=4401)
            return

        await websocket.accept()
        client: PiRpcClient | None = None
        try:
            init_msg = await websocket.receive_text()
            init = json.loads(init_msg)
            if init.get("type") != "init":
                await websocket.close(code=4400)
                return
            agent_name = init.get("agent")
            session_name = init.get("session") or "main"
            session_file = init.get("session_file")

            if agent_scope and agent_name != agent_scope:
                await websocket.close(code=4404)
                return
            if session_scope and session_name != session_scope:
                await websocket.close(code=4404)
                return
            if session_file_scope and session_file and session_file != session_file_scope:
                await websocket.close(code=4404)
                return

            agent = _get_agent(agent_name)
            if not agent:
                await websocket.close(code=4404)
                return

            session_dir = agent.path / "sessions" / session_name
            session_dir.mkdir(parents=True, exist_ok=True)
            ensure_session_meta(session_dir)

            session_path = None
            if session_file:
                candidate = agent.path / "sessions" / session_name / session_file
                if not candidate.exists():
                    await websocket.close(code=4404)
                    return
                session_path = candidate

            llm_config = load_llm_config(agent.path)

            client = PiRpcClient(
                settings=settings,
                agent_dir=agent.path,
                session_name=session_name,
                session_file=session_path,
                llm_config=llm_config,
                read_only_tools=read_only_tools,
            )
            await client.start()

            async def event_forwarder():
                assert client
                async for event in client.events():
                    await websocket.send_text(json.dumps({"type": event.type, "data": event.data}))

            forwarder = asyncio.create_task(event_forwarder())

            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                if msg.get("type") == "prompt":
                    if read_only:
                        await websocket.close(code=4403)
                        break
                    prompt = msg.get("message", "")
                    images = msg.get("images")
                    if not prompt and not images:
                        continue
                    if prompt:
                        update_session_title_from_prompt(session_dir, prompt)
                    update_session_meta(session_dir)
                    payload = {"type": "prompt", "message": prompt}
                    if images:
                        payload["images"] = images
                    async with client.lock:
                        await client.send(payload)
                else:
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            if client:
                await client.close()
            if "forwarder" in locals():
                forwarder.cancel()

    return app


def run_server(
    *,
    host: str,
    port: int,
    agent: str | None = None,
    session: str | None = None,
    session_file: str | None = None,
    read_only: bool = False,
    read_only_tools: bool = False,
):
    import uvicorn

    settings = ServerSettings.load()
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None

    is_public_bind = host in {"0.0.0.0", "::"} or (addr is not None and not addr.is_loopback)
    if is_public_bind and not settings.auth_token:
        print(
            "WARNING: public/non-local bind detected without PIPAL_AUTH_TOKEN.\n"
            "The server will run unauthenticated.\n"
            "Before exposing access, set PIPAL_AUTH_TOKEN and place the service "
            "behind network controls (TLS/reverse proxy, firewall, or VPN)."
        )

    app = create_app(
        agent_scope=agent,
        session_scope=session,
        session_file_scope=session_file,
        read_only=read_only,
        read_only_tools=read_only_tools,
    )
    uvicorn.run(app, host=host, port=port)
