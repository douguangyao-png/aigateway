# MVP Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-process Python gateway that exposes `POST /v1/chat/completions` (OpenAI-compatible shape) backed by Claude Agent SDK using the host's Claude Code OAuth subscription, plus a single-file HTML tryout page at `GET /`.

**Architecture:** FastAPI + uvicorn. One handler converts an OpenAI Chat Completions request into Agent SDK inputs, awaits the SDK iterator, accumulates `AssistantMessage.TextBlock` text and `ResultMessage.usage`, then formats an OpenAI ChatCompletion response. No DB, no auth, no streaming.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, claude-agent-sdk (0.2.x), pytest, pytest-asyncio. Single venv at `/root/aigateway/.venv` (already created and SDK pre-installed).

**Reference spec:** `docs/superpowers/specs/2026-05-16-mvp-proxy-design.md`

---

## File Structure

| Path | Purpose |
|---|---|
| `requirements.txt` | Pinned runtime + test dependencies |
| `errors.py` | Single helper: build OpenAI-shaped `JSONResponse` error envelope |
| `converters.py` | Pure functions: `openai_to_claude_sdk_args`, `claude_sdk_result_to_openai` |
| `claude_client.py` | Async wrapper around `claude_agent_sdk.query()`; returns `(text, usage)` |
| `main.py` | FastAPI app, routes (`/`, `/v1/chat/completions`), request validation |
| `static/index.html` | Single-page tryout UI (HTML + CSS + JS in one file) |
| `tests/__init__.py` | Empty marker |
| `tests/test_converters.py` | Pure-function tests for converters |
| `tests/test_claude_client.py` | claude_client tests with mocked SDK |
| `tests/test_main.py` | FastAPI route tests with mocked `claude_client.call_claude` |
| `README.md` | Setup + run + curl examples |

All `.py` files live at repo root (flat layout) — matches spec, simplest for MVP.

---

## Conventions

- **Python:** use `/root/aigateway/.venv/bin/python` and `/root/aigateway/.venv/bin/pytest` throughout (do not rely on `PATH`).
- **Working directory:** all commands run from `/root/aigateway`.
- **Commits:** small, frequent. Co-Author line required.
- **Style:** type hints on every public function. No comments unless explaining non-obvious why.

---

### Task 1: Bootstrap project skeleton

**Files:**
- Create: `requirements.txt`
- Create: `tests/__init__.py`
- Verify: `/root/aigateway/.venv` already exists with `claude-agent-sdk` installed

- [ ] **Step 1: Create `requirements.txt`**

```
fastapi==0.115.5
uvicorn[standard]==0.32.1
claude-agent-sdk>=0.2.82
pytest==8.3.4
pytest-asyncio==0.24.0
httpx==0.28.1
```

(`httpx` is for FastAPI's `TestClient`. SDK install already pulled it transitively, but pinning here makes the requirement explicit.)

- [ ] **Step 2: Install / verify**

Run: `cd /root/aigateway && .venv/bin/pip install -r requirements.txt`
Expected: all "already satisfied" or fresh install ok, exit 0.

- [ ] **Step 3: Create `tests/__init__.py` (empty file)**

```
```

(empty)

- [ ] **Step 4: Verify pytest can be invoked with zero tests**

Run: `cd /root/aigateway && .venv/bin/pytest -q`
Expected: `no tests ran` or `collected 0 items`, exit 0 or 5 (5 = no tests collected). Either is acceptable for this bootstrap step.

- [ ] **Step 5: Commit**

```bash
cd /root/aigateway
git add requirements.txt tests/__init__.py
git commit -m "$(cat <<'EOF'
chore: bootstrap python project (requirements + tests dir)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `errors.py` helper

**Files:**
- Create: `tests/test_errors.py`
- Create: `errors.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_errors.py`:

```python
import json

from errors import error_response


def test_error_response_shape():
    resp = error_response("bad model", "invalid_request_error", 400)
    assert resp.status_code == 400
    body = json.loads(resp.body)
    assert body == {
        "error": {"message": "bad model", "type": "invalid_request_error"}
    }


def test_error_response_500():
    resp = error_response("oops", "server_error", 500)
    assert resp.status_code == 500
    body = json.loads(resp.body)
    assert body["error"]["type"] == "server_error"
```

- [ ] **Step 2: Run, see import fail**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'errors'`.

- [ ] **Step 3: Implement `errors.py`**

```python
from fastapi.responses import JSONResponse


def error_response(message: str, error_type: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type}},
    )
```

- [ ] **Step 4: Run, see pass**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_errors.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /root/aigateway
git add errors.py tests/test_errors.py
git commit -m "$(cat <<'EOF'
feat: add error_response helper for OpenAI-shape error envelopes

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `converters.openai_to_claude_sdk_args` happy paths

**Files:**
- Create: `tests/test_converters.py`
- Create: `converters.py`

- [ ] **Step 1: Write first failing test (basic case with system + multi-turn)**

Create `tests/test_converters.py`:

```python
import pytest

from converters import openai_to_claude_sdk_args


def test_openai_to_claude_sdk_args_basic():
    body = {
        "model": "claude-haiku-4-5-20251001",
        "messages": [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
        ],
    }
    args = openai_to_claude_sdk_args(body)
    assert args["model"] == "claude-haiku-4-5-20251001"
    assert args["system_prompt"] == "You are concise."
    assert args["prompt"] == (
        "User: Hello\n"
        "Assistant: Hi there\n"
        "User: How are you?"
    )
```

- [ ] **Step 2: Run, see import fail**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_converters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'converters'`.

- [ ] **Step 3: Implement minimal `converters.py`**

```python
def openai_to_claude_sdk_args(body: dict) -> dict:
    messages = body["messages"]
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    convo = [m for m in messages if m["role"] in ("user", "assistant")]
    prompt_lines = []
    for m in convo:
        prefix = "User" if m["role"] == "user" else "Assistant"
        prompt_lines.append(f"{prefix}: {m['content']}")
    return {
        "model": body["model"],
        "system_prompt": "\n\n".join(system_parts) if system_parts else None,
        "prompt": "\n".join(prompt_lines),
    }
```

- [ ] **Step 4: Run, see pass**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_converters.py -v`
Expected: 1 passed.

- [ ] **Step 5: Add no-system test**

Append to `tests/test_converters.py`:

```python
def test_openai_to_claude_sdk_args_no_system():
    body = {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "hi"}],
    }
    args = openai_to_claude_sdk_args(body)
    assert args["system_prompt"] is None
    assert args["prompt"] == "User: hi"
```

- [ ] **Step 6: Add multiple-system test**

Append:

```python
def test_openai_to_claude_sdk_args_multiple_system():
    body = {
        "model": "claude-opus-4-7",
        "messages": [
            {"role": "system", "content": "Be polite."},
            {"role": "system", "content": "Use bullet points."},
            {"role": "user", "content": "tell me a fact"},
        ],
    }
    args = openai_to_claude_sdk_args(body)
    assert args["system_prompt"] == "Be polite.\n\nUse bullet points."
```

- [ ] **Step 7: Run, see all pass**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_converters.py -v`
Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
cd /root/aigateway
git add converters.py tests/test_converters.py
git commit -m "$(cat <<'EOF'
feat: convert OpenAI request body to Claude SDK args (happy paths)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `converters.openai_to_claude_sdk_args` validation errors

**Files:**
- Modify: `converters.py`
- Modify: `tests/test_converters.py`

- [ ] **Step 1: Add failing validation tests**

Append to `tests/test_converters.py`:

```python
def test_openai_to_claude_sdk_args_empty_messages_raises():
    with pytest.raises(ValueError, match="messages must be a non-empty array"):
        openai_to_claude_sdk_args({"model": "claude-haiku-4-5-20251001", "messages": []})


def test_openai_to_claude_sdk_args_missing_messages_raises():
    with pytest.raises(ValueError, match="messages must be a non-empty array"):
        openai_to_claude_sdk_args({"model": "claude-haiku-4-5-20251001"})


def test_openai_to_claude_sdk_args_last_message_not_user_raises():
    body = {
        "model": "claude-haiku-4-5-20251001",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    }
    with pytest.raises(ValueError, match="last message must be role=user"):
        openai_to_claude_sdk_args(body)


def test_openai_to_claude_sdk_args_only_system_raises():
    body = {
        "model": "claude-haiku-4-5-20251001",
        "messages": [{"role": "system", "content": "be helpful"}],
    }
    with pytest.raises(ValueError, match="last message must be role=user"):
        openai_to_claude_sdk_args(body)
```

- [ ] **Step 2: Run, see new tests fail**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_converters.py -v`
Expected: 4 new tests FAIL (no validation raised); 3 prior tests still pass.

- [ ] **Step 3: Add validation to `converters.py`**

Replace the body of `openai_to_claude_sdk_args` in `converters.py`:

```python
def openai_to_claude_sdk_args(body: dict) -> dict:
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) == 0:
        raise ValueError("messages must be a non-empty array")
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    convo = [m for m in messages if m["role"] in ("user", "assistant")]
    if not convo or convo[-1]["role"] != "user":
        raise ValueError("last message must be role=user")
    prompt_lines = []
    for m in convo:
        prefix = "User" if m["role"] == "user" else "Assistant"
        prompt_lines.append(f"{prefix}: {m['content']}")
    return {
        "model": body["model"],
        "system_prompt": "\n\n".join(system_parts) if system_parts else None,
        "prompt": "\n".join(prompt_lines),
    }
```

- [ ] **Step 4: Run, all pass**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_converters.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /root/aigateway
git add converters.py tests/test_converters.py
git commit -m "$(cat <<'EOF'
feat: validate messages array in openai_to_claude_sdk_args

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `converters.claude_sdk_result_to_openai`

**Files:**
- Modify: `converters.py`
- Modify: `tests/test_converters.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_converters.py`:

```python
def test_claude_sdk_result_to_openai_basic():
    from converters import claude_sdk_result_to_openai

    result = claude_sdk_result_to_openai(
        text="Hello there",
        usage={"input_tokens": 10, "output_tokens": 5},
        model="claude-haiku-4-5-20251001",
    )
    assert result["object"] == "chat.completion"
    assert result["model"] == "claude-haiku-4-5-20251001"
    assert result["id"].startswith("chatcmpl-")
    assert isinstance(result["created"], int)
    assert result["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello there"},
            "finish_reason": "stop",
        }
    ]
    assert result["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }


def test_claude_sdk_result_to_openai_missing_usage():
    from converters import claude_sdk_result_to_openai

    result = claude_sdk_result_to_openai(text="x", usage=None, model="claude-opus-4-7")
    assert result["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def test_claude_sdk_result_to_openai_partial_usage():
    from converters import claude_sdk_result_to_openai

    result = claude_sdk_result_to_openai(
        text="x",
        usage={"input_tokens": 7},
        model="claude-haiku-4-5-20251001",
    )
    assert result["usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 0,
        "total_tokens": 7,
    }
```

- [ ] **Step 2: Run, see fail**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_converters.py -v`
Expected: 3 new tests FAIL with `ImportError: cannot import name 'claude_sdk_result_to_openai'`.

- [ ] **Step 3: Implement**

Append to `converters.py`:

```python
import time
import uuid


def claude_sdk_result_to_openai(text: str, usage: dict | None, model: str) -> dict:
    prompt_tokens = (usage or {}).get("input_tokens", 0) or 0
    completion_tokens = (usage or {}).get("output_tokens", 0) or 0
    return {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
```

Move the `import time` and `import uuid` to the top of `converters.py` for cleanliness.

- [ ] **Step 4: Run, see pass**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_converters.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
cd /root/aigateway
git add converters.py tests/test_converters.py
git commit -m "$(cat <<'EOF'
feat: convert Claude SDK result to OpenAI ChatCompletion shape

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `claude_client.call_claude` with mocked SDK

**Files:**
- Create: `tests/test_claude_client.py`
- Create: `claude_client.py`

- [ ] **Step 1: Write failing test using monkeypatch of SDK `query`**

Create `tests/test_claude_client.py`:

```python
import pytest


def _make_text_block(text):
    from claude_agent_sdk import TextBlock
    return TextBlock(text=text)


def _make_assistant(*texts):
    from claude_agent_sdk import AssistantMessage
    return AssistantMessage(
        content=[_make_text_block(t) for t in texts],
        model="claude-haiku-4-5-20251001",
        parent_tool_use_id=None,
        error=None,
        usage=None,
        message_id=None,
        stop_reason=None,
        session_id=None,
        uuid=None,
    )


def _make_result(is_error=False, usage=None, errors=None):
    from claude_agent_sdk import ResultMessage
    return ResultMessage(
        subtype="success" if not is_error else "error",
        duration_ms=10,
        duration_api_ms=5,
        is_error=is_error,
        num_turns=1,
        session_id="s",
        stop_reason="end_turn",
        total_cost_usd=0.0,
        usage=usage,
        result=None,
        structured_output=None,
        model_usage=None,
        permission_denials=None,
        deferred_tool_use=None,
        errors=errors,
        api_error_status=None,
        uuid=None,
    )


@pytest.mark.asyncio
async def test_call_claude_accumulates_text_and_usage(monkeypatch):
    import claude_client

    async def fake_query(*, prompt, options, transport=None):
        yield _make_assistant("Hello, ", "world!")
        yield _make_result(usage={"input_tokens": 3, "output_tokens": 2})

    monkeypatch.setattr(claude_client, "query", fake_query)

    text, usage = await claude_client.call_claude(
        prompt="hi", system_prompt=None, model="claude-haiku-4-5-20251001"
    )
    assert text == "Hello, world!"
    assert usage == {"input_tokens": 3, "output_tokens": 2}


@pytest.mark.asyncio
async def test_call_claude_raises_on_is_error(monkeypatch):
    import claude_client

    async def fake_query(*, prompt, options, transport=None):
        yield _make_result(is_error=True, errors=["something broke"])

    monkeypatch.setattr(claude_client, "query", fake_query)

    with pytest.raises(claude_client.ClaudeError, match="something broke"):
        await claude_client.call_claude(
            prompt="hi", system_prompt=None, model="claude-haiku-4-5-20251001"
        )
```

- [ ] **Step 2: Configure pytest-asyncio**

Create `pytest.ini` at repo root:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Run, see import fail**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_claude_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_client'`.

- [ ] **Step 4: Implement `claude_client.py`**

```python
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)


class ClaudeError(Exception):
    pass


async def call_claude(
    prompt: str,
    system_prompt: str | None,
    model: str,
) -> tuple[str, dict | None]:
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        max_turns=1,
        allowed_tools=[],
        permission_mode="default",
        setting_sources=None,
    )
    text_chunks: list[str] = []
    usage: dict | None = None
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    text_chunks.append(block.text)
        elif isinstance(msg, ResultMessage):
            if msg.is_error:
                detail = ", ".join(msg.errors or []) or "claude sdk reported error"
                raise ClaudeError(detail)
            usage = msg.usage
    return "".join(text_chunks), usage
```

- [ ] **Step 5: Run, see pass**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_claude_client.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /root/aigateway
git add claude_client.py tests/test_claude_client.py pytest.ini
git commit -m "$(cat <<'EOF'
feat: claude_client.call_claude wraps Agent SDK query()

Single-turn call, tools disabled, accumulates AssistantMessage.TextBlock
text and ResultMessage.usage. Raises ClaudeError on is_error=True.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: FastAPI app and route — happy path with mocked client

**Files:**
- Create: `tests/test_main.py`
- Create: `main.py`

- [ ] **Step 1: Write failing happy-path test**

Create `tests/test_main.py`:

```python
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
```

- [ ] **Step 2: Run, see fail**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`.

- [ ] **Step 3: Implement minimum `main.py`**

```python
from fastapi import FastAPI, Request

from claude_client import call_claude
from converters import (
    claude_sdk_result_to_openai,
    openai_to_claude_sdk_args,
)
from errors import error_response

app = FastAPI()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    args = openai_to_claude_sdk_args(body)
    text, usage = await call_claude(
        prompt=args["prompt"],
        system_prompt=args["system_prompt"],
        model=args["model"],
    )
    return claude_sdk_result_to_openai(text=text, usage=usage, model=args["model"])
```

- [ ] **Step 4: Run, see pass**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_main.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /root/aigateway
git add main.py tests/test_main.py
git commit -m "$(cat <<'EOF'
feat: FastAPI POST /v1/chat/completions happy path

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Request validation errors

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Add failing validation tests**

Append to `tests/test_main.py`:

```python
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
```

- [ ] **Step 2: Run, see fails**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_main.py -v`
Expected: 5 new tests FAIL (no validation in handler yet); 1 prior happy-path test still passes.

- [ ] **Step 3: Update `main.py` handler with validation**

Replace `chat_completions` body in `main.py`:

```python
import json

from fastapi import FastAPI, Request

from claude_client import call_claude
from converters import (
    claude_sdk_result_to_openai,
    openai_to_claude_sdk_args,
)
from errors import error_response

app = FastAPI()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return error_response("invalid request body", "invalid_request_error", 400)

    if not isinstance(body, dict):
        return error_response("invalid request body", "invalid_request_error", 400)

    if body.get("stream"):
        return error_response(
            "streaming not supported in MVP", "invalid_request_error", 400
        )

    model = body.get("model")
    if not isinstance(model, str):
        return error_response("model is required", "invalid_request_error", 400)
    if not model.startswith("claude-"):
        return error_response(
            f"unsupported model: {model}", "invalid_request_error", 400
        )

    try:
        args = openai_to_claude_sdk_args(body)
    except ValueError as exc:
        return error_response(str(exc), "invalid_request_error", 400)

    text, usage = await call_claude(
        prompt=args["prompt"],
        system_prompt=args["system_prompt"],
        model=args["model"],
    )
    return claude_sdk_result_to_openai(text=text, usage=usage, model=args["model"])
```

- [ ] **Step 4: Run, see all pass**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_main.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /root/aigateway
git add main.py tests/test_main.py
git commit -m "$(cat <<'EOF'
feat: validate chat completions request (stream, model, messages, body)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: SDK error path → 502 / 429

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Add failing error-path tests**

Append to `tests/test_main.py`:

```python
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
```

- [ ] **Step 2: Run, see fails (uncaught exception → 500)**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_main.py -v`
Expected: 2 new tests FAIL.

- [ ] **Step 3: Wrap the SDK call in try/except**

In `main.py`, replace the call_claude block and add the import:

```python
from claude_client import call_claude, ClaudeError
```

And replace the call section at the bottom of `chat_completions`:

```python
    try:
        text, usage = await call_claude(
            prompt=args["prompt"],
            system_prompt=args["system_prompt"],
            model=args["model"],
        )
    except ClaudeError as exc:
        return error_response(f"claude error: {exc}", "upstream_error", 502)
    except Exception as exc:
        return error_response(f"claude sdk error: {exc}", "upstream_error", 502)

    return claude_sdk_result_to_openai(text=text, usage=usage, model=args["model"])
```

- [ ] **Step 4: Run, see all pass**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_main.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /root/aigateway
git add main.py tests/test_main.py
git commit -m "$(cat <<'EOF'
feat: map ClaudeError and other SDK exceptions to 502 upstream_error

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Tryout page — `GET /` + static HTML

**Files:**
- Create: `static/index.html`
- Modify: `main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write failing route test**

Append to `tests/test_main.py`:

```python
def test_root_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    text = resp.text
    assert "AI Gateway" in text
    assert "claude-haiku-4-5-20251001" in text
    assert "claude-sonnet-4-6" in text
    assert "claude-opus-4-7" in text
    assert "<textarea" in text
```

- [ ] **Step 2: Run, see fail (404)**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_main.py::test_root_serves_html -v`
Expected: FAIL with 404 not 200.

- [ ] **Step 3: Create `static/index.html`**

```html
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>AI Gateway 试用</title>
<style>
  :root { color-scheme: light; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 760px;
    margin: 2rem auto;
    padding: 0 1rem;
    color: #1a1a1a;
  }
  h1 { font-size: 1.4rem; margin-bottom: 1rem; }
  label { display: block; margin: 0.5rem 0 0.25rem; font-weight: 600; }
  select, textarea, button {
    font: inherit;
    border: 1px solid #ccc;
    border-radius: 4px;
    padding: 0.5rem;
    box-sizing: border-box;
  }
  select { width: 100%; }
  textarea { width: 100%; min-height: 8rem; resize: vertical; }
  button {
    background: #2563eb;
    color: white;
    border: none;
    padding: 0.6rem 1.2rem;
    cursor: pointer;
    margin-top: 0.5rem;
  }
  button:disabled { background: #9ca3af; cursor: not-allowed; }
  .panel {
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 0.75rem;
    margin-top: 1rem;
    white-space: pre-wrap;
    min-height: 4rem;
  }
  .meta { font-size: 0.85rem; color: #555; margin-top: 0.5rem; }
  .error { color: #b91c1c; }
</style>
</head>
<body>
  <h1>AI Gateway 试用</h1>

  <label for="model">模型</label>
  <select id="model">
    <option value="claude-haiku-4-5-20251001">claude-haiku-4-5-20251001</option>
    <option value="claude-sonnet-4-6">claude-sonnet-4-6</option>
    <option value="claude-opus-4-7">claude-opus-4-7</option>
  </select>

  <label for="prompt">提问</label>
  <textarea id="prompt" placeholder="输入你的问题…"></textarea>

  <button id="send">发送</button>

  <label>回复</label>
  <div id="output" class="panel"></div>
  <div id="meta" class="meta"></div>

<script>
const sendBtn = document.getElementById("send");
const out = document.getElementById("output");
const meta = document.getElementById("meta");

sendBtn.addEventListener("click", async () => {
  const model = document.getElementById("model").value;
  const promptText = document.getElementById("prompt").value.trim();
  if (!promptText) return;

  sendBtn.disabled = true;
  out.classList.remove("error");
  out.textContent = "…思考中";
  meta.textContent = "";

  const t0 = performance.now();
  try {
    const resp = await fetch("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: promptText }],
      }),
    });
    const data = await resp.json();
    const elapsed = ((performance.now() - t0) / 1000).toFixed(1);

    if (!resp.ok) {
      out.classList.add("error");
      out.textContent = data.error?.message || `HTTP ${resp.status}`;
      meta.textContent = `耗时 ${elapsed}s`;
      return;
    }

    out.textContent = data.choices?.[0]?.message?.content || "(empty response)";
    const u = data.usage || {};
    meta.textContent =
      `用量: prompt=${u.prompt_tokens ?? 0}  ` +
      `completion=${u.completion_tokens ?? 0}  ` +
      `total=${u.total_tokens ?? 0}   |   耗时 ${elapsed}s`;
  } catch (err) {
    out.classList.add("error");
    out.textContent = String(err);
  } finally {
    sendBtn.disabled = false;
  }
});
</script>
</body>
</html>
```

- [ ] **Step 4: Add `GET /` route in `main.py`**

Add at the top of `main.py`:

```python
from pathlib import Path
from fastapi.responses import FileResponse
```

Add after `app = FastAPI()`:

```python
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")
```

- [ ] **Step 5: Run, see pass**

Run: `cd /root/aigateway && .venv/bin/pytest tests/test_main.py -v`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
cd /root/aigateway
git add static/index.html main.py tests/test_main.py
git commit -m "$(cat <<'EOF'
feat: add GET / tryout page with model dropdown + token usage

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Live end-to-end smoke test

**Files:** (no source changes, validation only)

- [ ] **Step 1: Start the server in background**

Run:
```bash
cd /root/aigateway
.venv/bin/uvicorn main:app --port 8090 --log-level info > /tmp/uvicorn.log 2>&1 &
echo $! > /tmp/uvicorn.pid
sleep 2
```

- [ ] **Step 2: Hit the tryout page**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8090/`
Expected: `200`.

- [ ] **Step 3: Hit the API path (requires host `claude` OAuth logged in)**

Run:
```bash
curl -s http://localhost:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","messages":[{"role":"user","content":"Reply with the word OK only."}]}' \
  | python3 -m json.tool
```

Expected: a JSON body with `"object": "chat.completion"`, `choices[0].message.content` containing "OK", `usage.total_tokens > 0`.

- [ ] **Step 4: Hit an error path**

Run:
```bash
curl -s -o /tmp/err.json -w "%{http_code}\n" http://localhost:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"x"}]}'
cat /tmp/err.json
```

Expected: `400` and `{"error":{"message":"unsupported model: gpt-4o","type":"invalid_request_error"}}`.

- [ ] **Step 5: Stop the server**

Run: `kill $(cat /tmp/uvicorn.pid) && rm /tmp/uvicorn.pid`

- [ ] **Step 6: Inspect log for surprises**

Run: `tail -40 /tmp/uvicorn.log`
Expected: only INFO-level startup + request lines, no tracebacks.

(No commit — this task only validates.)

---

### Task 12: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# AI Gateway (MVP — Claude only)

OpenAI-compatible HTTP gateway in front of the Claude Agent SDK. Uses the
host's Claude Code OAuth login (subscription quota), not an Anthropic API
key. See `docs/superpowers/specs/2026-05-16-mvp-proxy-design.md` for the
design.

## Prerequisites

- Python 3.11+
- Node.js + Claude Code CLI:
  ```
  npm install -g @anthropic-ai/claude-code
  claude   # complete OAuth login once
  ```

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/uvicorn main:app --port 8090
```

Open <http://localhost:8090/> for the tryout page, or call the API:

```bash
curl -s http://localhost:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","messages":[{"role":"user","content":"say hi"}]}'
```

## Test

```bash
.venv/bin/pytest -q
```

## Supported models

The model must start with `claude-`. The tryout dropdown lists:

- `claude-haiku-4-5-20251001`
- `claude-sonnet-4-6`
- `claude-opus-4-7`

Other Anthropic model names with `claude-` prefix are accepted but
untested.

## Known limitations

- No streaming (request with `stream: true` is rejected with 400).
- No `max_tokens` / `temperature` control (the Agent SDK does not expose
  these; client-supplied values are silently ignored).
- Per-request agent context overhead is ~25k cached tokens (Claude Code
  agent system prompt). First call latency ~10–15s.
- No auth. Bind to localhost or a trusted network only.
```

- [ ] **Step 2: Commit**

```bash
cd /root/aigateway
git add README.md
git commit -m "$(cat <<'EOF'
docs: add README with setup, run, and test instructions

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Final test sweep + push

- [ ] **Step 1: Run full test suite**

Run: `cd /root/aigateway && .venv/bin/pytest -q`
Expected: all tests pass (errors: 2, converters: 10, claude_client: 2, main: 9 = 23 total).

- [ ] **Step 2: Push to GitHub**

Run: `git -C /root/aigateway push origin main`
Expected: push succeeds.

- [ ] **Step 3: Final manual UI verification**

Open <http://localhost:8090/> in a browser (after `uvicorn main:app --port 8090`), pick a model, type a question, click 发送, confirm a response appears with token-usage line. If running on a remote host, use SSH port-forward: `ssh -L 8090:localhost:8090 <host>`.

No commit (verification only).

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `POST /v1/chat/completions` OpenAI shape | 7, 8 |
| Route by `claude-` prefix, else 400 | 8 |
| `stream=true` → 400 | 8 |
| `messages` validation (empty, last not user) | 4, 8 |
| Convert system messages to `system_prompt` (joined `\n\n`) | 3 |
| Convert user/assistant turns to single prompt with `User:` / `Assistant:` prefix | 3 |
| `ClaudeAgentOptions` with `max_turns=1`, `allowed_tools=[]`, `permission_mode="default"`, `setting_sources=None` | 6 |
| Drop `max_tokens` / `temperature` from request | (implicit — converters don't pass them; main doesn't either) |
| `ResultMessage.is_error` → 502 | 6, 9 |
| SDK exceptions → 502 upstream_error | 9 |
| Response shape: `id`, `object`, `created`, `choices[0]`, `usage` | 5 |
| `finish_reason: "stop"` constant | 5 |
| `GET /` returns single-file HTML | 10 |
| HTML: model dropdown, textarea, output, token usage | 10 |
| Unit tests for converters (happy + validation) | 3, 4, 5 |
| Unit tests for claude_client with mocked SDK | 6 |
| Unit tests for main routes with mocked client | 7, 8, 9, 10 |
| README with curl + setup | 12 |
| End-to-end live test | 11 |

No gaps. Spec items intentionally not covered: `429` on rate limit (the SDK error path catches all SDK exceptions as 502 since reliable rate-limit detection requires SDK-specific exception types we haven't confirmed; documented as known limitation for second stage). The spec's error table includes 429 as a target, but since `claude-agent-sdk` 0.2.82 routes rate-limit failures through general exception types rather than a dedicated class, mapping to 429 reliably needs investigation we defer.

**Placeholder scan:** no TBDs or "implement later" — every step has concrete code or commands.

**Type consistency:**
- `openai_to_claude_sdk_args(body: dict) -> dict` returning keys `model`, `system_prompt`, `prompt` — consistent in Tasks 3, 4, 7, 8.
- `claude_sdk_result_to_openai(text: str, usage: dict | None, model: str) -> dict` — consistent in Tasks 5, 7.
- `call_claude(prompt, system_prompt, model) -> (text, usage)` — consistent in Tasks 6, 7.
- `ClaudeError` exception class — defined in Task 6, used in Tasks 6, 9.
- `error_response(message, error_type, status_code)` — defined Task 2, used Tasks 8, 9.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-16-mvp-proxy-implementation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task with two-stage review between tasks. Best when you want each task verified independently before moving on.
2. **Inline Execution** — execute tasks in this session with checkpoints. Faster overall but harder to recover if a task derails.

Which approach?
