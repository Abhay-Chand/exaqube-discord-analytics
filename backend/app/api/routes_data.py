from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.data_access import queries as q
from app.models.schemas import ChannelOut, DailyActivityPoint, HourlyDistributionPoint, ServerOut

router = APIRouter(prefix="/api", tags=["data"])


@router.get("/servers", response_model=list[ServerOut])
async def get_servers(request: Request):
    rows = await q.list_servers(request.app.state.pools.app)
    return rows


@router.get("/servers/{server_id}/channels", response_model=list[ChannelOut])
async def get_channels(server_id: str, request: Request):
    rows = await q.list_channels(request.app.state.pools.app, server_id)
    if not rows:
        # ambiguous whether the server doesn't exist or just has no channels;
        # check explicitly rather than silently returning [] either way.
        exists = await request.app.state.pools.app.fetchval(
            "SELECT 1 FROM servers WHERE server_id = $1", server_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail=f"No such server: {server_id}")
    return rows


@router.get("/servers/{server_id}/daily-activity", response_model=list[DailyActivityPoint])
async def get_daily_activity(server_id: str, request: Request):
    return await q.daily_activity(request.app.state.pools.app, server_id)


@router.get("/servers/{server_id}/hourly-distribution", response_model=list[HourlyDistributionPoint])
async def get_hourly_distribution(server_id: str, request: Request):
    return await q.hourly_message_distribution(request.app.state.pools.app, server_id)


@router.get("/servers/{server_id}/messages")
async def get_messages(server_id: str, request: Request, limit: int = 50, offset: int = 0):
    if limit > 200:
        raise HTTPException(status_code=422, detail="limit must be <= 200")
    return await q.sample_messages(request.app.state.pools.app, server_id, limit=limit, offset=offset)
