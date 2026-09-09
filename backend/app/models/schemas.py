from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel


class ServerOut(BaseModel):
    server_id: str
    server_name: str
    region: str | None
    premium_tier: int
    approximate_member_count: int
    creation_date: datetime.datetime


class ChannelOut(BaseModel):
    channel_id: str
    server_id: str
    channel_name: str
    channel_type: str
    nsfw: bool


class DailyActivityPoint(BaseModel):
    date: datetime.date
    messages: int


class HourlyDistributionPoint(BaseModel):
    hour: int
    message_count: int


class ChatRequest(BaseModel):
    session_id: uuid.UUID | None = None
    message: str


class PinCreateRequest(BaseModel):
    title: str
    query_sql: str
    chart_args: dict  # chart_type, x_field, y_field, series_field?, agg, sort_by_value?, top_n?


class PinOut(BaseModel):
    pin_id: uuid.UUID
    title: str
    plugin_args: dict  # {"query_sql": ..., "chart_args": {...}}
    result_cache: dict | None
    created_at: datetime.datetime
