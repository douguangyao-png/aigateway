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
