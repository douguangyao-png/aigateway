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


def test_openai_to_claude_sdk_args_no_system():
    body = {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "hi"}],
    }
    args = openai_to_claude_sdk_args(body)
    assert args["system_prompt"] is None
    assert args["prompt"] == "User: hi"


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
