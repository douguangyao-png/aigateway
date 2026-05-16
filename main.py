import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse

from claude_client import call_claude, ClaudeError
from converters import (
    claude_sdk_result_to_openai,
    openai_to_claude_sdk_args,
)
from errors import error_response

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


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


if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8090")),
    )
