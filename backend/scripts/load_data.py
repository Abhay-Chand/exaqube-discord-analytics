"""
Idempotent loader for the Discord analytics dataset.

Run it as many times as you like: every insert is `ON CONFLICT ... DO UPDATE`
keyed on the table's natural primary key, so re-running never duplicates rows
and always converges to whatever's currently in the CSVs.

Known data-quality issues in this dataset, and what we do about them:

1. `afk_timeout` (servers), `topic` (channels), `avatar_hash`/`roles` (members)
   have real, meaningful nulls (e.g. a bot with no roles, a channel with no
   topic set). We load them as SQL NULL, not empty string or 0 — collapsing
   "no timeout configured" into `0` would be a lie the schema shouldn't tell.

2. `members.csv` has 52 rows that collide on the natural key
   (server_id, user_id) but describe two genuinely different fake people
   (different usernames, join dates, message counts). This looks like a
   user-id collision in the dataset's synthetic generator, not a duplicate
   export. We don't have a source of truth for which is "correct", so we
   apply a simple, reproducible rule: last row in file order wins, which is
   exactly what `INSERT ... ON CONFLICT DO UPDATE` does for free when we
   insert in file order. This is a real data loss (52 profiles out of 2827
   are shadowed) and we say so here and in the README instead of hiding it.

3. All source timestamps are naive (no UTC offset). We treat them as UTC at
   the boundary and store `timestamptz`, so every timestamp in the DB is
   unambiguous regardless of where the API or agent runs.

4. `discriminator` is sometimes out of Discord's real 4-digit range in the
   synthetic data; we don't validate it, since it's cosmetic and unused by
   any query in this project.
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
from pathlib import Path

import asyncpg
import pandas as pd

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", SCRIPT_DIR.parent.parent / "data"))
SCHEMA_SQL = SCRIPT_DIR / "schema.sql"

# Owner/migration connection — the loader intentionally does NOT run as the
# read-only agent role or the app_rw role; it needs DDL + write on every table.
DATABASE_URL = os.environ.get(
    "MIGRATE_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/discord_analytics"
)


def clean_value(v):
    """NaN/NaT -> None; numpy scalars -> plain python. asyncpg has no idea
    what a numpy.float64 or a pandas NaT is."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if pd.isna(v):
        return None
    if hasattr(v, "item"):  # numpy scalar
        return v.item()
    return v


def rows_for(df: pd.DataFrame, columns: list[str]) -> list[tuple]:
    return [tuple(clean_value(v) for v in row) for row in df[columns].itertuples(index=False, name=None)]


async def ensure_database(admin_dsn: str, dbname: str) -> None:
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", dbname)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{dbname}"')
            print(f"Created database {dbname}")
    finally:
        await conn.close()


async def load() -> None:
    from urllib.parse import urlsplit

    parts = urlsplit(DATABASE_URL)
    dbname = parts.path.lstrip("/")
    admin_dsn = DATABASE_URL.replace(f"/{dbname}", "/postgres")
    await ensure_database(admin_dsn, dbname)

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(SCHEMA_SQL.read_text())
        print("Schema applied (idempotent).")

        # ---- servers ----
        servers = pd.read_csv(DATA_DIR / "servers.csv")
        servers["creation_date"] = pd.to_datetime(servers["creation_date"], utc=True)
        cols = [
            "server_id", "server_name", "owner_id", "creation_date", "region",
            "verification_level", "default_message_notifications", "explicit_content_filter",
            "system_channel_id", "afk_channel_id", "afk_timeout", "widget_enabled",
            "premium_tier", "premium_subscription_count", "approximate_member_count",
            "approximate_presence_count",
        ]
        await conn.executemany(
            f"""INSERT INTO servers ({",".join(cols)}) VALUES ({",".join(f"${i+1}" for i in range(len(cols)))})
                ON CONFLICT (server_id) DO UPDATE SET
                {",".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "server_id")}""",
            rows_for(servers, cols),
        )
        print(f"servers: upserted {len(servers)} rows")

        # ---- channels ----
        channels = pd.read_csv(DATA_DIR / "channels.csv")
        cols = ["channel_id", "server_id", "channel_name", "channel_type", "topic",
                "nsfw", "rate_limit_per_user", "position"]
        # a null channel_name is unusable downstream (it's the display label
        # everywhere); fall back to the id rather than dropping the channel.
        channels["channel_name"] = channels["channel_name"].fillna(channels["channel_id"])
        await conn.executemany(
            f"""INSERT INTO channels ({",".join(cols)}) VALUES ({",".join(f"${i+1}" for i in range(len(cols)))})
                ON CONFLICT (channel_id) DO UPDATE SET
                {",".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "channel_id")}""",
            rows_for(channels, cols),
        )
        print(f"channels: upserted {len(channels)} rows")

        # ---- members ---- (see module docstring re: the 52 colliding keys)
        members = pd.read_csv(DATA_DIR / "members.csv")
        members["join_date"] = pd.to_datetime(members["join_date"], utc=True)
        members["last_active"] = pd.to_datetime(members["last_active"], utc=True)
        cols = ["server_id", "user_id", "username", "display_name", "discriminator",
                "avatar_hash", "is_bot", "join_date", "last_active", "roles",
                "messages_sent", "voice_minutes", "is_owner"]
        await conn.executemany(
            f"""INSERT INTO members ({",".join(cols)}) VALUES ({",".join(f"${i+1}" for i in range(len(cols)))})
                ON CONFLICT (server_id, user_id) DO UPDATE SET
                {",".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in ("server_id", "user_id"))}""",
            rows_for(members, cols),
        )
        dupe_count = int(members.duplicated(subset=["server_id", "user_id"]).sum())
        print(f"members: upserted {len(members)} rows ({dupe_count} key collisions resolved as last-row-wins)")

        # ---- messages ----
        messages = pd.read_csv(DATA_DIR / "messages_sample.csv")
        messages["timestamp"] = pd.to_datetime(messages["timestamp"], utc=True)
        cols = ["message_id", "server_id", "channel_id", "user_id", "timestamp", "content",
                "has_attachment", "has_embed", "reaction_count", "is_pinned", "length"]
        await conn.executemany(
            f"""INSERT INTO messages ({",".join(cols)}) VALUES ({",".join(f"${i+1}" for i in range(len(cols)))})
                ON CONFLICT (message_id) DO UPDATE SET
                {",".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "message_id")}""",
            rows_for(messages, cols),
        )
        print(f"messages: upserted {len(messages)} rows")

        # ---- daily_stats ----
        daily = pd.read_csv(DATA_DIR / "daily_stats.csv")
        daily["date"] = pd.to_datetime(daily["date"]).dt.date
        daily["is_weekend"] = daily["is_weekend"].astype(bool)
        cols = ["server_id", "date", "total_messages", "new_members", "active_members",
                "total_members", "day_of_week", "is_weekend"]
        await conn.executemany(
            f"""INSERT INTO daily_stats ({",".join(cols)}) VALUES ({",".join(f"${i+1}" for i in range(len(cols)))})
                ON CONFLICT (server_id, date) DO UPDATE SET
                {",".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in ("server_id", "date"))}""",
            rows_for(daily, cols),
        )
        print(f"daily_stats: upserted {len(daily)} rows")

        # ---- channel_daily_stats ----
        cds = pd.read_csv(DATA_DIR / "channel_daily_stats.csv")
        cds["date"] = pd.to_datetime(cds["date"]).dt.date
        cols = ["channel_id", "server_id", "date", "message_count", "active_users"]
        await conn.executemany(
            f"""INSERT INTO channel_daily_stats ({",".join(cols)}) VALUES ({",".join(f"${i+1}" for i in range(len(cols)))})
                ON CONFLICT (channel_id, date) DO UPDATE SET
                {",".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in ("channel_id", "date"))}""",
            rows_for(cds, cols),
        )
        print(f"channel_daily_stats: upserted {len(cds)} rows")

        counts = await conn.fetch(
            "SELECT 'servers' t, count(*) c FROM servers UNION ALL SELECT 'channels', count(*) FROM channels "
            "UNION ALL SELECT 'members', count(*) FROM members UNION ALL SELECT 'messages', count(*) FROM messages "
            "UNION ALL SELECT 'daily_stats', count(*) FROM daily_stats "
            "UNION ALL SELECT 'channel_daily_stats', count(*) FROM channel_daily_stats"
        )
        print("\nFinal row counts:")
        for r in counts:
            print(f"  {r['t']}: {r['c']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(load())
    sys.exit(0)
