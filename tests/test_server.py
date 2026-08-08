import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pipal.server import create_app, run_server


def test_server_refuses_non_local_bind_without_token(monkeypatch):
    monkeypatch.delenv("PIPAL_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("AUTH_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="Refusing non-local bind"):
        run_server(host="0.0.0.0", port=8000)

    with pytest.raises(SystemExit, match="Refusing non-local bind"):
        run_server(host="example.com", port=8000)


def test_server_allows_loopback_without_token(monkeypatch):
    monkeypatch.delenv("PIPAL_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    called = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, *, host, port: called.update(host=host, port=port))

    run_server(host="127.0.0.1", port=8123)

    assert called == {"host": "127.0.0.1", "port": 8123}


def test_server_refuses_non_local_bind_with_short_token(monkeypatch):
    monkeypatch.setenv("PIPAL_AUTH_TOKEN", "long-test-token")

    with pytest.raises(SystemExit, match="shorter than 32 characters"):
        run_server(host="0.0.0.0", port=8123)


def test_server_allows_non_local_bind_with_strong_token(monkeypatch):
    monkeypatch.setenv("PIPAL_AUTH_TOKEN", "a" * 32)
    called = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, *, host, port: called.update(host=host, port=port))

    run_server(host="0.0.0.0", port=8123)

    assert called == {"host": "0.0.0.0", "port": 8123}


def test_rest_auth_requires_a_strict_bearer_token(monkeypatch):
    monkeypatch.setenv("PIPAL_AUTH_TOKEN", "test-token")
    client = TestClient(create_app())

    assert client.get("/agents").status_code == 401
    assert client.get("/agents", headers={"Authorization": "not-bearer test-token"}).status_code == 401
    assert client.get("/agents", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/agents", headers={"Authorization": "Bearer test-token"}).status_code == 200
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer test-token"}).status_code == 200


def test_cors_is_opt_in_and_never_wildcard(monkeypatch):
    monkeypatch.delenv("PIPAL_CORS_ORIGINS", raising=False)
    client = TestClient(create_app())
    response = client.options(
        "/agents", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert response.headers.get("access-control-allow-origin") is None

    monkeypatch.setenv("PIPAL_CORS_ORIGINS", "https://ui.example/")
    client = TestClient(create_app())
    response = client.options(
        "/agents", headers={"Origin": "https://ui.example", "Access-Control-Request-Method": "GET"}
    )
    assert response.headers["access-control-allow-origin"] == "https://ui.example"
    assert response.headers.get("access-control-allow-credentials") is None

    for invalid_origin in ("*", "null", "https://ui.example/path", "ftp://ui.example"):
        monkeypatch.setenv("PIPAL_CORS_ORIGINS", invalid_origin)
        with pytest.raises(ValueError, match="explicit http\\(s\\) origins"):
            create_app()


def test_websocket_rejects_missing_query_and_disallowed_origin_tokens(monkeypatch):
    monkeypatch.setenv("PIPAL_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("PIPAL_CORS_ORIGINS", "https://ui.example")
    client = TestClient(create_app())

    for path, headers in [
        ("/ws", {}),
        ("/ws?token=test-token", {}),
        ("/ws", {"Authorization": "Basic test-token"}),
    ]:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(path, headers=headers):
                pass
        assert exc.value.code == 4401

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws", headers={"Authorization": "Bearer test-token", "Origin": "https://evil.example"}
        ):
            pass
    assert exc.value.code == 4403

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws", headers={"Authorization": "Bearer test-token", "Origin": "https://ui.example"}
        ) as websocket:
            websocket.send_text('{"type":"init","agent":"missing"}')
            websocket.receive_text()
    assert exc.value.code == 4404
