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
