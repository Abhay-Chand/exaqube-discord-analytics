from __future__ import annotations

import time

import asyncpg
from pydantic import BaseModel, Field

from app.agent.sql_guard import SQLGuardError, validate_select
from app.plugins.base import Plugin, PluginContext, PluginError, PluginResult
from app.plugins.registry import register_plugin

PREVIEW_ROWS = 15


class QueryArgs(BaseModel):
    sql: str = Field(..., description="A single read-only PostgreSQL SELECT statement.")
    row_cap: int = Field(
        default=5000, ge=1, le=5000,
        description="Maximum rows to return. Server clamps this to 5000 regardless of what's requested.",
    )


@register_plugin
class QueryPlugin(Plugin):
    name = "query"
    description = (
        "Execute a read-only SQL SELECT against the analytics database and return the results as structured "
        "data. The database contains: servers, channels, members, messages, daily_stats (per server per day), "
        "channel_daily_stats (per channel per day). Write the SQL yourself based on the user's question — this "
        "tool validates it (single SELECT only, no writes, row-capped) and executes it. If the query is invalid "
        "or fails, you'll get a structured error back and can retry with corrected SQL, bounded attempts."
    )
    input_model = QueryArgs
    produces = "result_set"

    async def execute(self, args: QueryArgs, ctx: PluginContext) -> PluginResult:
        try:
            guarded = validate_select(args.sql, row_cap=min(args.row_cap, ctx.row_cap))
        except SQLGuardError as e:
            raise PluginError(e.code, e.message, retryable=e.retryable) from e

        start = time.monotonic()
        try:
            async with ctx.db_pool.acquire() as conn:
                records = await conn.fetch(guarded.sql)
        except asyncpg.PostgresError as e:
            # Real Postgres errors (unknown column, type mismatch, etc) are
            # exactly the case the agent should be able to retry against —
            # the message tells it what's wrong.
            raise PluginError("SQL_EXECUTION_ERROR", str(e), retryable=True) from e
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)

        rows = [dict(r) for r in records]
        # jsonify non-JSON-native types (datetimes, Decimal, UUID) up front so
        # every downstream consumer (chart plugin, SSE payload) gets plain types.
        rows = [_jsonify_row(r) for r in rows]

        columns = list(rows[0].keys()) if rows else _columns_from_guarded(guarded.sql)
        preview = rows[:PREVIEW_ROWS]

        ref = ctx.store.put(kind="result_set", full_data=rows, preview=preview, row_count=len(rows))

        display_text = (
            f"Query returned {len(rows)} row(s) in {elapsed_ms}ms"
            + (f" (capped at {guarded.row_cap})" if len(rows) == guarded.row_cap else "")
            + f". Columns: {', '.join(columns) if columns else '(none)'}."
        )
        return PluginResult(ref=ref, display_text=display_text)


def _jsonify_row(row: dict) -> dict:
    import datetime
    import decimal
    import uuid as uuidlib

    out = {}
    for k, v in row.items():
        if isinstance(v, (datetime.datetime, datetime.date)):
            out[k] = v.isoformat()
        elif isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif isinstance(v, uuidlib.UUID):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def _columns_from_guarded(sql: str) -> list[str]:
    return []
