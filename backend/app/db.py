from __future__ import annotations

import json

import asyncpg


async def _init_connection(conn: asyncpg.Connection) -> None:
    # Without this, asyncpg hands back raw JSON text for jsonb columns and
    # refuses a python dict as a jsonb parameter outright. Registering the
    # codec once per connection means pinned_charts.plugin_args round-trips
    # as a plain dict everywhere else in the app.
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


class Pools:
    app: asyncpg.Pool  # role app_rw — data-serving endpoints, pin CRUD
    agent: asyncpg.Pool  # role agent_ro — the query plugin ONLY

    def __init__(self, app_pool: asyncpg.Pool, agent_pool: asyncpg.Pool):
        self.app = app_pool
        self.agent = agent_pool

    @classmethod
    async def create(cls, app_dsn: str, agent_dsn: str) -> "Pools":
        app_pool = await asyncpg.create_pool(app_dsn, min_size=1, max_size=10, init=_init_connection)
        agent_pool = await asyncpg.create_pool(agent_dsn, min_size=1, max_size=10, init=_init_connection)
        return cls(app_pool, agent_pool)

    async def close(self) -> None:
        await self.app.close()
        await self.agent.close()
