from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.provider import build_provider_from_settings
from app.api import routes_chat, routes_data, routes_pins
from app.config import load_settings
from app.db import Pools
from app.errors import install_error_handlers
from app.logging_mw import TraceIdMiddleware, configure_logging
from app.plugins.registry import discover_plugins

logger = logging.getLogger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()  # raises loudly if config is missing/invalid — see config.py
    configure_logging(settings.log_level)

    app.state.settings = settings
    app.state.plugin_registry = discover_plugins()
    logger.info("plugins_loaded names=%s", list(app.state.plugin_registry.keys()))

    app.state.pools = await Pools.create(settings.app_database_url, settings.agent_database_url)
    app.state.llm_provider = build_provider_from_settings(settings)
    app.state.chat_sessions = {}  # session_id -> ChatSession, in-memory (see routes_chat.py)

    logger.info("startup_complete")
    try:
        yield
    finally:
        await app.state.pools.close()
        logger.info("shutdown_complete")


app = FastAPI(title="Discord Analytics Agent API", lifespan=lifespan)

app.add_middleware(TraceIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tightened via settings.cors_origins in a real deployment; permissive here for local dev
    allow_methods=["*"],
    allow_headers=["*"],
)
install_error_handlers(app)

app.include_router(routes_data.router)
app.include_router(routes_chat.router)
app.include_router(routes_pins.router)


@app.get("/health")
async def health():
    """Means something: actually checks both DB pools can run a query, not
    just that the process is up."""
    try:
        await app.state.pools.app.fetchval("SELECT 1")
        await app.state.pools.agent.fetchval("SELECT 1")
    except Exception as e:  # noqa: BLE001
        return {"status": "unhealthy", "detail": str(e)}
    return {"status": "healthy", "plugins": list(app.state.plugin_registry.keys())}
