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
