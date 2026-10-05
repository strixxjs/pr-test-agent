"""LLM client interfaces and Groq integration."""

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from groq import Groq, RateLimitError


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str | None = None


@dataclass
class LLMReply:
    content: str | None
    tool_calls: list[ToolCall]
    prompt_tokens: int
    completion_tokens: int


class LLMClient(Protocol):
    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMReply:
        """Send chat messages and tool definitions, returning the model reply."""
        ...


class GroqClient:
    """Client for Groq API using the official SDK."""

    def __init__(
        self, api_key: str | None = None, model: str | None = None
    ) -> None:
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise ValueError("GROQ_API_KEY environment variable is not set")
        chosen_model = model or os.environ.get("GROQ_MODEL")
        if not chosen_model:
            raise ValueError("GROQ_MODEL environment variable is not set")

        self.client = Groq(api_key=key)
        self.model = chosen_model

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMReply:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 2000,
        }
        if tools:
            kwargs["tools"] = tools

        attempts = 0
        while True:
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except RateLimitError as exc:
                attempts += 1
                if attempts > 3:
                    raise
                retry_after: str | None = None
                if exc.response is not None and exc.response.headers is not None:
                    retry_after = exc.response.headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after is not None else 1.0
                except (ValueError, TypeError):
                    delay = 1.0
                delay = max(0.1, min(delay, 30.0))
                time.sleep(delay)

        choice = response.choices[0]
        content = choice.message.content

        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0

        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tc_id = tc.id
                tc_name = tc.function.name
                tc_raw = tc.function.arguments or ""
                try:
                    parsed = json.loads(tc_raw)
                    if isinstance(parsed, dict):
                        tc_args = parsed
                        raw_arg = None
                    else:
                        tc_args = {}
                        raw_arg = tc_raw
                except (json.JSONDecodeError, TypeError):
                    tc_args = {}
                    raw_arg = tc_raw

                tool_calls.append(
                    ToolCall(
                        id=tc_id,
                        name=tc_name,
                        arguments=tc_args,
                        raw_arguments=raw_arg,
                    )
                )

        return LLMReply(
            content=content,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
