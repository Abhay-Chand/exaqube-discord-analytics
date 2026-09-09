"""
The core loop. Deliberately thin: it knows nothing about SQL, charts, or any
specific plugin — it only knows the `Plugin` interface (base.py) and the
`LLMProvider` interface (provider.py). Adding a plugin or swapping the LLM
vendor never requires touching this file; that's the whole point of the two
abstractions it sits on top of.

Retry policy: a single tool call gets up to MAX_RETRIES_PER_CALL chances
where the *same logical request* fails (invalid args, guard rejection, SQL
error) — each failure is fed back to the model as a tool result containing
the structured error, and the model decides what to do next (retry with
different arguments, try a different approach, or give up and say so). The
loop as a whole is bounded by MAX_ITERATIONS round trips to the LLM, so a
model that keeps calling tools without ever producing a final answer can't
run forever.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

from app.agent.events import ev
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.provider import LLMProvider, Message, ProviderEvent
from app.plugins.base import ArtifactStore, PluginContext, PluginError

logger = logging.getLogger("agent")

MAX_ITERATIONS = 8
MAX_RETRIES_PER_CALL = 2


class ChatSession:
    """Holds one conversation's history + artifact store. Kept in-memory,
    keyed by session_id, in the route layer — see the module docstring in
    plugins/base.py (ArtifactStore) for why this is intentionally not
    persisted: pins copy out what they need, so losing this on restart
    only loses in-flight chat context, not anything durable."""

    def __init__(self):
        self.messages: list[Message] = [Message(role="system", content=SYSTEM_PROMPT)]
        self.store = ArtifactStore()


async def run_turn(
    session: ChatSession,
    user_text: str,
    registry: dict,
    provider: LLMProvider,
    db_pool,
    row_cap: int,
    trace_id: str,
) -> AsyncIterator[dict]:
    session.messages.append(Message(role="user", content=user_text))
    tool_schemas = [p.tool_schema() for p in registry.values()]
    ctx = PluginContext(store=session.store, db_pool=db_pool, row_cap=row_cap)

    # per-call-id retry counters, reset each turn
    retry_counts: dict[str, int] = {}

    for iteration in range(MAX_ITERATIONS):
        yield ev("status", stage="thinking", iteration=iteration)

        assistant_text_parts: list[str] = []
        tool_calls = None
        provider_error = None

        async for pev in provider.stream(session.messages, tool_schemas):
            if pev.kind == "text_delta":
                assistant_text_parts.append(pev.text)
                yield ev("token", text=pev.text)
            elif pev.kind == "tool_calls":
                tool_calls = pev.tool_calls
            elif pev.kind == "error":
                provider_error = pev.error
            elif pev.kind == "stop":
                pass

        if provider_error:
            logger.error("provider_error trace_id=%s error=%s", trace_id, provider_error)
            yield ev("error", message=f"The language model backend failed: {provider_error}")
            yield ev("done")
            return

        assistant_text = "".join(assistant_text_parts)

        if not tool_calls:
            # Final answer for this turn.
            session.messages.append(Message(role="assistant", content=assistant_text))
            yield ev("assistant_message", text=assistant_text)
            yield ev("done")
            return

        # Record the assistant's tool-call request in history, then execute each.
        session.messages.append(Message(
            role="assistant",
            content=assistant_text or None,
            tool_calls=[{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in tool_calls],
        ))

        for tc in tool_calls:
            call_key = f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True, default=str)}"
            yield ev("tool_call", call_id=tc.id, name=tc.name, arguments=tc.arguments)

            plugin = registry.get(tc.name)
            if plugin is None:
                error_payload = {"code": "UNKNOWN_TOOL", "message": f"No such tool: {tc.name}", "retryable": False}
                yield ev("tool_error", call_id=tc.id, **error_payload)
                session.messages.append(Message(role="tool", tool_call_id=tc.id, content=json.dumps(error_payload)))
                continue

            try:
                args = plugin.parse_arguments(tc.arguments)
                result = await asyncio.wait_for(plugin.execute(args, ctx), timeout=15.0)
            except PluginError as e:
                retry_counts[call_key] = retry_counts.get(call_key, 0) + 1
                logger.warning(
                    "tool_error trace_id=%s tool=%s code=%s retry=%d",
                    trace_id, tc.name, e.code, retry_counts[call_key],
                )
                error_payload = e.to_dict()
                if retry_counts[call_key] > MAX_RETRIES_PER_CALL:
                    error_payload["retryable"] = False
                    error_payload["message"] += " (retry limit reached — do not attempt this exact call again)"
                yield ev("tool_error", call_id=tc.id, **error_payload)
                session.messages.append(Message(role="tool", tool_call_id=tc.id, content=json.dumps(error_payload)))
                continue
            except asyncio.TimeoutError:
                error_payload = {"code": "TIMEOUT", "message": f"{tc.name} timed out.", "retryable": False}
                yield ev("tool_error", call_id=tc.id, **error_payload)
                session.messages.append(Message(role="tool", tool_call_id=tc.id, content=json.dumps(error_payload)))
                continue

            yield ev("tool_result", call_id=tc.id, name=tc.name, display_text=result.display_text, ref=result.ref.summary())
            session.messages.append(Message(
                role="tool", tool_call_id=tc.id,
                content=json.dumps({"display_text": result.display_text, "ref": result.ref.summary()}),
            ))

    # Exhausted MAX_ITERATIONS without a final answer.
    surrender = "I wasn't able to reach a final answer within the allotted number of tool calls. Please rephrase or narrow the question."
    session.messages.append(Message(role="assistant", content=surrender))
    yield ev("assistant_message", text=surrender)
    yield ev("done")
