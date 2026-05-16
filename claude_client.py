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
        max_turns=6,
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
