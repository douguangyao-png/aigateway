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
- Rate-limit responses from the Claude subscription quota are returned
  as `502 upstream_error` (no dedicated 429 mapping in MVP).
