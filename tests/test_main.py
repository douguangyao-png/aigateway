import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import main

    async def fake_call_claude(prompt, system_prompt, model):
        assert model == "claude-haiku-4-5-20251001"
        return ("hi from mock", {"input_tokens": 4, "output_tokens": 2})

    monkeypatch.setattr(main, "call_claude", fake_call_claude)
    return TestClient(main.app)


def test_chat_completion_happy_path(client):
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "claude-haiku-4-5-20251001",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "hi from mock"
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["usage"] == {
        "prompt_tokens": 4,
        "completion_tokens": 2,
        "total_tokens": 6,
    }


def test_rejects_stream_true(client):
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "claude-haiku-4-5-20251001",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert "streaming" in body["error"]["message"]


def test_rejects_unsupported_model(client):
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert "unsupported model" in body["error"]["message"]


def test_rejects_missing_model(client):
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 400


def test_rejects_invalid_messages(client):
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "claude-haiku-4-5-20251001", "messages": []},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "messages must be a non-empty array" in body["error"]["message"]


def test_rejects_non_json_body(client):
    resp = client.post(
        "/v1/chat/completions",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "invalid request body"


def test_claude_error_returns_502(monkeypatch):
    import main
    from claude_client import ClaudeError

    async def fake_call_claude(prompt, system_prompt, model):
        raise ClaudeError("oauth expired")

    monkeypatch.setattr(main, "call_claude", fake_call_claude)
    c = TestClient(main.app)
    resp = c.post(
        "/v1/chat/completions",
        json={
            "model": "claude-haiku-4-5-20251001",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["type"] == "upstream_error"
    assert "oauth expired" in body["error"]["message"]


def test_generic_sdk_exception_returns_502(monkeypatch):
    import main

    async def fake_call_claude(prompt, system_prompt, model):
        raise RuntimeError("subprocess died")

    monkeypatch.setattr(main, "call_claude", fake_call_claude)
    c = TestClient(main.app)
    resp = c.post(
        "/v1/chat/completions",
        json={
            "model": "claude-haiku-4-5-20251001",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["type"] == "upstream_error"
    assert "subprocess died" in body["error"]["message"]
