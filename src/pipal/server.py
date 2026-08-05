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
    ensure_topic_meta,
    update_topic_meta,
    update_topic_title_from_prompt,
)
from .server_models import AgentInfo, SessionInfo
from .topic_storage import topics_root, topic_dir, topic_sessions_dir, validate_topic_name
from .server_rpc import PiRpcClient


def create_app(
    *,
    agent_scope: str | None = None,
    topic_scope: str | None = None,
    session_scope: str | None = None,
    read_only: bool = False,
    read_only_tools: bool = False,
) -> FastAPI:
    settings = ServerSettings.load()
    app = FastAPI(title="pipal server", version="0.2.0")

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

    def _list_topics(agent: AgentInfo) -> list[dict]:
        topics: list[dict] = []
        for path in topics_root(agent.path).iterdir():
            if not path.is_dir() or (topic_scope and path.name != topic_scope):
                continue
            meta = ensure_topic_meta(path)
            topics.append({"name": path.name, "path": path, **meta})
        return sorted(topics, key=lambda item: item.get("updated_at", ""), reverse=True)

    def _list_sessions(agent: AgentInfo, topic_name: str) -> list[SessionInfo]:
        files = sorted(topic_sessions_dir(agent.path, topic_name).glob("*.jsonl"), reverse=True)
        if session_scope:
            files = [path for path in files if path.name == session_scope]
        return [SessionInfo(name=path.name, path=path) for path in files]

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

    def _load_topic_history(agent: AgentInfo, topic_name: str) -> list[dict]:
        history: list[dict] = []
        for session in reversed(_list_sessions(agent, topic_name)):
            history.extend(_load_history_from_file(session.path))
        return history

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

    @app.get("/agents/{agent_name}/topics")
    async def get_topics(agent_name: str):
        agent = _get_agent(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return [
            {
                "name": item["name"],
                "title": item.get("title"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
            for item in _list_topics(agent)
        ]

    @app.get("/agents/{agent_name}/topics/{topic_name}/history")
    async def get_topic_history(agent_name: str, topic_name: str):
        agent = _get_agent(agent_name)
        if not agent or (topic_scope and topic_name != topic_scope):
            raise HTTPException(status_code=404, detail="Topic not found")
        try:
            validate_topic_name(topic_name)
        except ValueError:
            raise HTTPException(status_code=404, detail="Topic not found")
        return {"messages": _load_topic_history(agent, topic_name)}

    @app.get("/agents/{agent_name}/topics/{topic_name}/sessions")
    async def get_sessions(agent_name: str, topic_name: str):
        agent = _get_agent(agent_name)
        if not agent or (topic_scope and topic_name != topic_scope):
            raise HTTPException(status_code=404, detail="Topic not found")
        try:
            return [{"name": item.name} for item in _list_sessions(agent, topic_name)]
        except ValueError:
            raise HTTPException(status_code=404, detail="Topic not found")

    @app.get("/agents/{agent_name}/topics/{topic_name}/sessions/{session_name}/history")
    async def get_session_history(agent_name: str, topic_name: str, session_name: str):
        agent = _get_agent(agent_name)
        if not agent or (topic_scope and topic_name != topic_scope):
            raise HTTPException(status_code=404, detail="Topic not found")
        if session_scope and session_name != session_scope:
            raise HTTPException(status_code=404, detail="Session not found")
        if Path(session_name).name != session_name:
            raise HTTPException(status_code=404, detail="Session not found")
        session_path = topic_sessions_dir(agent.path, topic_name) / session_name
        if not session_path.is_file() or session_path.suffix != ".jsonl":
            raise HTTPException(status_code=404, detail="Session not found")
        return {"messages": _load_history_from_file(session_path)}

    @app.post("/agents/{agent_name}/topics")
    async def create_topic(agent_name: str):
        if read_only:
            raise HTTPException(status_code=403, detail="Read-only mode")
        agent = _get_agent(agent_name)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        topic_name = uuid.uuid4().hex[:8]
        current_topic_dir = topic_dir(agent.path, topic_name)
        ensure_topic_meta(current_topic_dir)
        return {"name": topic_name}

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
            topic_name = init.get("topic") or topic_scope or "main"
            session_name = init.get("session") or session_scope

            if agent_scope and agent_name != agent_scope:
                await websocket.close(code=4404)
                return
            if topic_scope and topic_name != topic_scope:
                await websocket.close(code=4404)
                return
            if session_scope and session_name != session_scope:
                await websocket.close(code=4404)
                return
            try:
                validate_topic_name(topic_name)
            except ValueError:
                await websocket.close(code=4404)
                return

            agent = _get_agent(agent_name)
            if not agent:
                await websocket.close(code=4404)
                return
            if read_only:
                await websocket.close(code=4403)
                return

            current_topic_dir = topic_dir(agent.path, topic_name)
            ensure_topic_meta(current_topic_dir)

            session_path = None
            if session_name:
                if Path(session_name).name != session_name:
                    await websocket.close(code=4404)
                    return
                candidate = topic_sessions_dir(agent.path, topic_name) / session_name
                if not candidate.is_file() or candidate.suffix != ".jsonl":
                    await websocket.close(code=4404)
                    return
                session_path = candidate

            llm_config = load_llm_config(agent.path)

            client = PiRpcClient(
                settings=settings,
                agent_dir=agent.path,
                topic_name=topic_name,
                session_file=session_path,
                llm_config=llm_config,
                read_only_tools=read_only_tools,
            )
            await client.start()

            async def event_forwarder():
                assert client
                async for event in client.events():
                    data = event.data
                    if event.type == "agent_end" and hasattr(client, "actual_session_file"):
                        data = {**data, "session": client.actual_session_file.name}
                    await websocket.send_text(json.dumps({"type": event.type, "data": data}))

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
                        update_topic_title_from_prompt(current_topic_dir, prompt)
                    update_topic_meta(current_topic_dir)
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
    topic: str | None = None,
    session: str | None = None,
    read_only: bool = False,
    read_only_tools: bool = False,
):
    import uvicorn

    settings = ServerSettings.load()
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None

    is_non_local_bind = not (addr.is_loopback if addr is not None else host.lower() == "localhost")
    if is_non_local_bind and not settings.auth_token:
        raise SystemExit(
            "Refusing non-local bind without PIPAL_AUTH_TOKEN. "
            "Set a long random token and use network controls such as TLS, a firewall, or a VPN."
        )

    app = create_app(
        agent_scope=agent,
        topic_scope=topic,
        session_scope=session,
        read_only=read_only,
        read_only_tools=read_only_tools,
    )
    uvicorn.run(app, host=host, port=port)
