from __future__ import annotations

import asyncpg


async def list_servers(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        "SELECT server_id, server_name, region, premium_tier, approximate_member_count, creation_date "
        "FROM servers ORDER BY server_name"
    )
    return [dict(r) for r in rows]


async def list_channels(pool: asyncpg.Pool, server_id: str) -> list[dict]:
    rows = await pool.fetch(
        "SELECT channel_id, server_id, channel_name, channel_type, nsfw FROM channels "
        "WHERE server_id = $1 ORDER BY position",
        server_id,
    )
    return [dict(r) for r in rows]


async def daily_activity(pool: asyncpg.Pool, server_id: str) -> list[dict]:
    """Channel activity per day for a server — a real GROUP BY/SUM in
    Postgres, not a re-aggregation of rows fetched into Python."""
    rows = await pool.fetch(
        """SELECT "date" AS date, SUM(message_count)::int AS messages
           FROM channel_daily_stats
           WHERE server_id = $1
           GROUP BY "date"
           ORDER BY "date" """,
        server_id,
    )
    return [dict(r) for r in rows]


async def hourly_message_distribution(pool: asyncpg.Pool, server_id: str) -> list[dict]:
    """Hour-of-day message distribution from the message sample — bucketing
    done with EXTRACT() in SQL, not with a Python Counter."""
    rows = await pool.fetch(
        """SELECT EXTRACT(HOUR FROM "timestamp")::int AS hour, COUNT(*)::int AS message_count
           FROM messages
           WHERE server_id = $1
           GROUP BY hour
           ORDER BY hour""",
        server_id,
    )
    return [dict(r) for r in rows]


async def sample_messages(pool: asyncpg.Pool, server_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    rows = await pool.fetch(
        """SELECT message_id, channel_id, user_id, "timestamp", content, reaction_count, is_pinned
           FROM messages WHERE server_id = $1 ORDER BY "timestamp" DESC LIMIT $2 OFFSET $3""",
        server_id, limit, offset,
    )
    return [dict(r) for r in rows]


async def list_pins(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        "SELECT pin_id, title, plugin_name, plugin_args, result_cache, created_at "
        "FROM pinned_charts ORDER BY created_at DESC"
    )
    return [dict(r) for r in rows]


async def create_pin(pool: asyncpg.Pool, title: str, plugin_name: str, plugin_args: dict, result_cache: dict | None) -> dict:
    row = await pool.fetchrow(
        """INSERT INTO pinned_charts (title, plugin_name, plugin_args, result_cache)
           VALUES ($1, $2, $3, $4)
           RETURNING pin_id, title, plugin_name, plugin_args, result_cache, created_at""",
        title, plugin_name, plugin_args, result_cache,
    )
    return dict(row)


async def delete_pin(pool: asyncpg.Pool, pin_id) -> bool:
    result = await pool.execute("DELETE FROM pinned_charts WHERE pin_id = $1", pin_id)
    return result != "DELETE 0"


async def update_pin_cache(pool: asyncpg.Pool, pin_id, result_cache: dict) -> None:
    await pool.execute("UPDATE pinned_charts SET result_cache = $2 WHERE pin_id = $1", pin_id, result_cache)
