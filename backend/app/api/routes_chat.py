from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from app.agent.core import ChatSession, run_turn
from app.models.schemas import ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger("chat")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    app_state = request.app.state
    session_id = body.session_id or uuid.uuid4()
    session = app_state.chat_sessions.get(session_id)
    if session is None:
        session = ChatSession()
        app_state.chat_sessions[session_id] = session

    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))

    async def event_stream():
        yield _sse({"event": "session", "session_id": str(session_id)})
        try:
            async for event in run_turn(
                session=session,
                user_text=body.message,
                registry=app_state.plugin_registry,
                provider=app_state.llm_provider,
                db_pool=app_state.pools.agent,
                row_cap=app_state.settings.row_cap,
                trace_id=trace_id,
            ):
                yield _sse(event)
        except Exception:  # noqa: BLE001 — never let a raw traceback hit an open SSE stream
            logger.exception("chat_stream_error trace_id=%s", trace_id)
            yield _sse({"event": "error", "message": "Internal error while processing the request."})
            yield _sse({"event": "done"})
        finally:
            # If the client disconnected mid-stream, FastAPI/Starlette raises
            # inside this generator (or simply stops iterating it) and we
            # land here either way — nothing external (a DB connection, an
            # asyncpg pool checkout) is held past this point because every
            # tool call in run_turn is awaited to completion or cancelled
            # via asyncio.wait_for's own timeout, never fire-and-forgotten.
            logger.info("chat_stream_closed trace_id=%s session_id=%s", trace_id, session_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
