from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from app.data_access import queries as q
from app.models.schemas import PinCreateRequest, PinOut
from app.pins import run_pin_spec
from app.plugins.base import PluginError

router = APIRouter(prefix="/api/pins", tags=["pins"])


@router.get("", response_model=list[PinOut])
async def list_pins(request: Request):
    rows = await q.list_pins(request.app.state.pools.app)
    return [
        {"pin_id": r["pin_id"], "title": r["title"], "plugin_args": r["plugin_args"],
         "result_cache": r["result_cache"], "created_at": r["created_at"]}
        for r in rows
    ]


@router.post("", response_model=PinOut, status_code=201)
async def create_pin(body: PinCreateRequest, request: Request):
    plugin_args = {"query_sql": body.query_sql, "chart_args": body.chart_args}
    try:
        chart_spec = await run_pin_spec(
            request.app.state.plugin_registry, request.app.state.pools.agent,
            request.app.state.settings.row_cap, body.query_sql, body.chart_args,
        )
    except PluginError as e:
        raise HTTPException(status_code=422, detail=e.to_dict()) from e

    row = await q.create_pin(request.app.state.pools.app, body.title, "chart", plugin_args, chart_spec)
    return {"pin_id": row["pin_id"], "title": row["title"], "plugin_args": row["plugin_args"],
            "result_cache": row["result_cache"], "created_at": row["created_at"]}


@router.post("/{pin_id}/refresh", response_model=PinOut)
async def refresh_pin(pin_id: uuid.UUID, request: Request):
    pins = await q.list_pins(request.app.state.pools.app)
    pin = next((p for p in pins if p["pin_id"] == pin_id), None)
    if pin is None:
        raise HTTPException(status_code=404, detail=f"No such pin: {pin_id}")

    try:
        chart_spec = await run_pin_spec(
            request.app.state.plugin_registry, request.app.state.pools.agent,
            request.app.state.settings.row_cap,
            pin["plugin_args"]["query_sql"], pin["plugin_args"]["chart_args"],
        )
    except PluginError as e:
        raise HTTPException(status_code=422, detail=e.to_dict()) from e

    await q.update_pin_cache(request.app.state.pools.app, pin_id, chart_spec)
    return {"pin_id": pin_id, "title": pin["title"], "plugin_args": pin["plugin_args"],
            "result_cache": chart_spec, "created_at": pin["created_at"]}


@router.delete("/{pin_id}", status_code=204)
async def delete_pin(pin_id: uuid.UUID, request: Request):
    deleted = await q.delete_pin(request.app.state.pools.app, pin_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No such pin: {pin_id}")
