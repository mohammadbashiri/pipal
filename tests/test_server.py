import pytest
import uvicorn

from pipal.server import run_server


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


def test_server_allows_non_local_bind_with_token(monkeypatch):
    monkeypatch.setenv("PIPAL_AUTH_TOKEN", "long-test-token")
    called = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, *, host, port: called.update(host=host, port=port))

    run_server(host="0.0.0.0", port=8123)

    assert called == {"host": "0.0.0.0", "port": 8123}
