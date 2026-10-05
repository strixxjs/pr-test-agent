from unittest.mock import MagicMock, patch

import httpx
import pytest
from groq import RateLimitError

from pr_test_agent.llm import GroqClient, LLMReply, ToolCall


def test_groq_client_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        GroqClient()

    monkeypatch.setenv("GROQ_API_KEY", "dummy_key")
    with pytest.raises(ValueError, match="GROQ_MODEL"):
        GroqClient()


def test_groq_client_chat_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "dummy_key")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    client = GroqClient()

    # Mock tool call response
    mock_choice = MagicMock()
    mock_choice.message.content = None

    tc1 = MagicMock()
    tc1.id = "call_1"
    tc1.function.name = "read_file"
    tc1.function.arguments = '{"path": "src/x.py"}'

    tc2 = MagicMock()
    tc2.id = "call_2"
    tc2.function.name = "write_test"
    tc2.function.arguments = "invalid_json{"

    mock_choice.message.tool_calls = [tc1, tc2]

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 25
    mock_response.usage.completion_tokens = 15

    client.client.chat.completions.create = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    reply = client.chat(messages=[{"role": "user", "content": "hello"}], tools=[])

    assert isinstance(reply, LLMReply)
    assert len(reply.tool_calls) == 2
    assert reply.tool_calls[0] == ToolCall(
        id="call_1",
        name="read_file",
        arguments={"path": "src/x.py"},
        raw_arguments=None,
    )
    assert reply.tool_calls[1] == ToolCall(
        id="call_2",
        name="write_test",
        arguments={},
        raw_arguments="invalid_json{",
    )
    assert reply.prompt_tokens == 25
    assert reply.completion_tokens == 15


def test_groq_client_429_retry_and_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "dummy_key")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    client = GroqClient()

    # Create dummy HTTP response for RateLimitError
    http_resp = httpx.Response(
        status_code=429,
        headers={"retry-after": "5"},
        request=httpx.Request("POST", "https://api.groq.com/chat"),
    )
    rate_err = RateLimitError("Rate limit exceeded", response=http_resp, body=None)

    client.client.chat.completions.create = MagicMock(side_effect=rate_err)  # type: ignore[method-assign]

    with patch("time.sleep") as mock_sleep, pytest.raises(RateLimitError):
        client.chat(messages=[], tools=[])

    assert mock_sleep.call_count == 3
    mock_sleep.assert_called_with(5.0)
