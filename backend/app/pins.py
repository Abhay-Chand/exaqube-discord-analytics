"""
What a pin actually is, and why: a pin stores the *plan* — the SQL that
produced the data plus the chart arguments — not a ref into any chat
session's in-memory ArtifactStore (those don't survive a restart and
shouldn't need to: the whole point of a pin outliving the conversation it
was created in).

Re-running a pin does NOT go back through the LLM — it's a fully
deterministic replay of `query` then `chart` with the stored arguments. The
LLM's job was to *decide* what to chart; once decided, running it again is
just calling two plugins directly through the same registry the agent uses.
"""
from __future__ import annotations

from app.plugins.base import ArtifactStore, PluginContext, PluginError


async def run_pin_spec(registry: dict, db_pool, row_cap: int, query_sql: str, chart_args: dict) -> dict:
    store = ArtifactStore()
    ctx = PluginContext(store=store, db_pool=db_pool, row_cap=row_cap)

    query_plugin = registry["query"]
    chart_plugin = registry["chart"]

    q_args = query_plugin.parse_arguments({"sql": query_sql})
    q_result = await query_plugin.execute(q_args, ctx)

    c_args = chart_plugin.parse_arguments({**chart_args, "ref_id": q_result.ref.ref_id})
    c_result = await chart_plugin.execute(c_args, ctx)

    return c_result.ref.full_data
