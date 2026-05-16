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
