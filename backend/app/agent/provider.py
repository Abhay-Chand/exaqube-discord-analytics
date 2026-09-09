"""
The agent core talks to `LLMProvider`, never to a specific vendor SDK. To
add Anthropic/local-model support, implement this ABC and switch
LLM_PROVIDER — nothing in agent/core.py changes. We only wire up OpenAI here
(per project scope), but the seam is real: `core.py` imports `ProviderEvent`
and calls `provider.stream(...)`, nothing OpenAI-specific leaks past this file.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class Message:
    role: Role
    content: str | None = None
    # for role="assistant" messages that called tools
    tool_calls: list[dict] | None = None  # [{"id","name","arguments": dict}]
    # for role="tool" messages: which call this is answering
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict


@dataclass
class ProviderEvent:
    kind: Literal["text_delta", "tool_calls", "stop", "error"]
    text: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    error: str | None = None


class LLMProvider(ABC):
    @abstractmethod
    async def stream(self, messages: list[Message], tools: list[dict]) -> AsyncIterator[ProviderEvent]: ...


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import AsyncOpenAI  # imported lazily so the module is importable without the package installed

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    def _to_openai_messages(self, messages: list[Message]) -> list[dict]:
        out = []
        for m in messages:
            if m.role == "assistant" and m.tool_calls:
                out.append({
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                        }
                        for tc in m.tool_calls
                    ],
                })
            elif m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""})
            else:
                out.append({"role": m.role, "content": m.content or ""})
        return out

    def _to_openai_tools(self, tools: list[dict]) -> list[dict]:
        return [
            {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in tools
        ]

    async def stream(self, messages: list[Message], tools: list[dict]) -> AsyncIterator[ProviderEvent]:
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=self._to_openai_messages(messages),
                tools=self._to_openai_tools(tools) if tools else None,
                stream=True,
            )
        except Exception as e:  # noqa: BLE001 - surfaced to the agent loop as a provider error event
            yield ProviderEvent(kind="error", error=f"LLM request failed: {e}")
            return

        # index -> accumulating {id, name, arguments_str}
        pending_tool_calls: dict[int, dict] = {}
        finish_reason = None

        try:
            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                if delta and delta.content:
                    yield ProviderEvent(kind="text_delta", text=delta.content)

                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        slot = pending_tool_calls.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                        if tc_delta.id:
                            slot["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            slot["name"] = tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            slot["arguments"] += tc_delta.function.arguments
        except Exception as e:  # noqa: BLE001 - mid-stream failure (network blip, etc)
            yield ProviderEvent(kind="error", error=f"LLM stream interrupted: {e}")
            return

        if finish_reason == "tool_calls" and pending_tool_calls:
            calls = []
            for slot in pending_tool_calls.values():
                try:
                    args = json.loads(slot["arguments"]) if slot["arguments"] else {}
                except json.JSONDecodeError:
                    args = {"_raw_unparsable_arguments": slot["arguments"]}
                calls.append(ToolCallRequest(id=slot["id"], name=slot["name"], arguments=args))
            yield ProviderEvent(kind="tool_calls", tool_calls=calls)
        else:
            yield ProviderEvent(kind="stop")


def build_provider_from_settings(settings) -> LLMProvider:
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")
        return OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)
    raise RuntimeError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")
