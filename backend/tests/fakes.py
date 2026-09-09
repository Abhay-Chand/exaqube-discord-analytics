"""
A scripted fake provider so the agent loop's mechanics (tool execution,
chaining, retry-on-error, final-answer detection) can be proven without a
real OpenAI key. Each call to `stream()` pops the next scripted response off
`self.script` — this lets a test simulate "model calls query, gets an error,
model retries with corrected SQL, model calls chart, model answers in text"
deterministically.
"""
from __future__ import annotations

from typing import AsyncIterator

from app.agent.provider import LLMProvider, Message, ProviderEvent, ToolCallRequest


class ScriptedProvider(LLMProvider):
    def __init__(self, script: list[dict]):
        # each script entry: {"text": str, "tool_calls": [{"name","arguments"}]} or {"text": str} for a final answer
        self.script = list(script)
        self.calls_made = 0

    async def stream(self, messages: list[Message], tools: list[dict]) -> AsyncIterator[ProviderEvent]:
        self.calls_made += 1
        if not self.script:
            yield ProviderEvent(kind="stop")
            return
        step = self.script.pop(0)
        if step.get("text"):
            yield ProviderEvent(kind="text_delta", text=step["text"])
        if step.get("tool_calls"):
            calls = [
                ToolCallRequest(id=f"call_{i}", name=c["name"], arguments=c["arguments"])
                for i, c in enumerate(step["tool_calls"])
            ]
            yield ProviderEvent(kind="tool_calls", tool_calls=calls)
        else:
            yield ProviderEvent(kind="stop")
