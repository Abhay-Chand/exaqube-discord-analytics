-- Discord analytics schema.
-- Grain / timezone note: all source timestamps in the dataset are naive
-- (no offset). We store them as `timestamptz` and treat naive input as UTC
-- at load time (`AT TIME ZONE 'UTC'`) so every timestamp in the DB is
-- unambiguous. `daily_stats.date` / `channel_daily_stats.date` are UTC
-- calendar dates (the generator's day boundary), stored as `date`.
-- Grain: one row per (server, day) in daily_stats, per (channel, day) in
-- channel_daily_stats, per message in messages. Aggregates in the API are
-- computed in SQL over these grains, never re-aggregated in Python.

CREATE TABLE IF NOT EXISTS servers (
    server_id                      TEXT PRIMARY KEY,
    server_name                    TEXT NOT NULL,
    owner_id                       TEXT,
    creation_date                  TIMESTAMPTZ NOT NULL,
    region                         TEXT,
    verification_level             SMALLINT NOT NULL DEFAULT 0,
    default_message_notifications  SMALLINT NOT NULL DEFAULT 0,
    explicit_content_filter        SMALLINT NOT NULL DEFAULT 0,
    system_channel_id              TEXT,
    afk_channel_id                 TEXT,
    afk_timeout                    INTEGER,
    widget_enabled                 BOOLEAN NOT NULL DEFAULT FALSE,
    premium_tier                   SMALLINT NOT NULL DEFAULT 0,
    premium_subscription_count     INTEGER NOT NULL DEFAULT 0,
    approximate_member_count       INTEGER NOT NULL DEFAULT 0,
    approximate_presence_count     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id              TEXT PRIMARY KEY,
    server_id                TEXT NOT NULL REFERENCES servers(server_id) ON DELETE CASCADE,
    channel_name             TEXT NOT NULL,
    channel_type             TEXT NOT NULL CHECK (channel_type IN ('text', 'voice')),
    topic                     TEXT,
    nsfw                      BOOLEAN NOT NULL DEFAULT FALSE,
    rate_limit_per_user       INTEGER NOT NULL DEFAULT 0,
    "position"                INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_channels_server ON channels(server_id);

-- Note: source user_id is only unique per-server (a Faker-generated id per
-- server membership, not a global Discord user id), so the natural key is
-- (server_id, user_id).
CREATE TABLE IF NOT EXISTS members (
    server_id        TEXT NOT NULL REFERENCES servers(server_id) ON DELETE CASCADE,
    user_id           TEXT NOT NULL,
    username          TEXT NOT NULL,
    display_name      TEXT,
    discriminator     SMALLINT,
    avatar_hash        TEXT,
    is_bot             BOOLEAN NOT NULL DEFAULT FALSE,
    join_date          TIMESTAMPTZ NOT NULL,
    last_active        TIMESTAMPTZ,
    roles              TEXT,           -- comma-separated in source; kept as raw text, exposed split in API layer
    messages_sent       INTEGER NOT NULL DEFAULT 0,
    voice_minutes        INTEGER NOT NULL DEFAULT 0,
    is_owner            BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (server_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_members_server_lastactive ON members(server_id, last_active DESC);

CREATE TABLE IF NOT EXISTS messages (
    message_id        TEXT PRIMARY KEY,
    server_id          TEXT NOT NULL REFERENCES servers(server_id) ON DELETE CASCADE,
    channel_id          TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    user_id             TEXT NOT NULL,
    "timestamp"          TIMESTAMPTZ NOT NULL,
    content              TEXT,
    has_attachment        BOOLEAN NOT NULL DEFAULT FALSE,
    has_embed            BOOLEAN NOT NULL DEFAULT FALSE,
    reaction_count        INTEGER NOT NULL DEFAULT 0,
    is_pinned            BOOLEAN NOT NULL DEFAULT FALSE,
    length                INTEGER NOT NULL DEFAULT 0
);
-- This is event-log data; nearly every interesting query buckets by time
-- within a server or channel, so these two composite indexes (leading on
-- the FK, trailing on time) are the ones that matter.
CREATE INDEX IF NOT EXISTS idx_messages_server_ts ON messages(server_id, "timestamp");
CREATE INDEX IF NOT EXISTS idx_messages_channel_ts ON messages(channel_id, "timestamp");

CREATE TABLE IF NOT EXISTS daily_stats (
    server_id        TEXT NOT NULL REFERENCES servers(server_id) ON DELETE CASCADE,
    "date"             DATE NOT NULL,
    total_messages     INTEGER NOT NULL DEFAULT 0,
    new_members         INTEGER NOT NULL DEFAULT 0,
    active_members       INTEGER NOT NULL DEFAULT 0,
    total_members         INTEGER NOT NULL DEFAULT 0,
    day_of_week            SMALLINT NOT NULL,
    is_weekend              BOOLEAN NOT NULL,
    PRIMARY KEY (server_id, "date")
);
CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON daily_stats("date");

CREATE TABLE IF NOT EXISTS channel_daily_stats (
    channel_id       TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    server_id         TEXT NOT NULL REFERENCES servers(server_id) ON DELETE CASCADE,
    "date"             DATE NOT NULL,
    message_count       INTEGER NOT NULL DEFAULT 0,
    active_users          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (channel_id, "date")
);
CREATE INDEX IF NOT EXISTS idx_chan_daily_stats_server_date ON channel_daily_stats(server_id, "date");

-- Pinned charts: a pin stores the *query*, not a rendered image, so it can
-- be re-run on load. plugin_name + plugin_args round-trip exactly what was
-- sent to the chart plugin originally; result_cache is an optional last-known
-- render so the dashboard has something to show before the re-run completes.
CREATE TABLE IF NOT EXISTS pinned_charts (
    pin_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              TEXT NOT NULL,
    plugin_name          TEXT NOT NULL,
    plugin_args           JSONB NOT NULL,
    result_cache            JSONB,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Roles. The agent NEVER connects as the owner/migration role.
-- `agent_ro`: strictly SELECT on data tables, statement_timeout enforced at
-- the role level (belt-and-suspenders with the per-request timeout set in
-- code), no access to pinned_charts writes.
-- `app_rw`: used by the FastAPI app itself for pin CRUD and is still not
-- the migration owner.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'agent_ro') THEN
        CREATE ROLE agent_ro LOGIN PASSWORD 'agent_ro_password';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_rw') THEN
        CREATE ROLE app_rw LOGIN PASSWORD 'app_rw_password';
    END IF;
END $$;

ALTER ROLE agent_ro SET statement_timeout = '5s';
ALTER ROLE agent_ro SET default_transaction_read_only = on;

GRANT CONNECT ON DATABASE discord_analytics TO agent_ro, app_rw;
GRANT USAGE ON SCHEMA public TO agent_ro, app_rw;
GRANT SELECT ON servers, channels, members, messages, daily_stats, channel_daily_stats TO agent_ro;
GRANT SELECT ON servers, channels, members, messages, daily_stats, channel_daily_stats TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON pinned_charts TO app_rw;
-- agent_ro explicitly gets nothing on pinned_charts: it cannot write, and it
-- cannot even read pins (pins are served by the API layer, not the agent's
-- own SQL tool), so a hostile prompt can't use pin data as a side channel.
