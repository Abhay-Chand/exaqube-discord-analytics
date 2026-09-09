from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Two separate DSNs by design: the API's own read/write access to
    # servers/channels/members/messages/daily_stats/*, and pin CRUD, goes
    # through app_database_url (role app_rw). The agent's SQL tool goes
    # through agent_database_url (role agent_ro) and NEVER app_rw — see
    # scripts/schema.sql for what each role can actually do at the DB level.
    app_database_url: str = Field(..., description="DSN for the app_rw role (API reads + pin CRUD).")
    agent_database_url: str = Field(..., description="DSN for the agent_ro role (agent's query tool only).")

    llm_provider: str = Field(default="openai")
    openai_api_key: str | None = Field(default=None)
    openai_model: str = Field(default="gpt-4o-mini")

    row_cap: int = Field(default=5000, ge=1, le=5000)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])

    log_level: str = Field(default="INFO")


def load_settings() -> Settings:
    try:
        return Settings()
    except Exception as e:  # noqa: BLE001
        # Fail loudly at startup, not with a 500 on the first request that
        # happens to touch the missing config.
        raise RuntimeError(
            f"Missing or invalid configuration — refusing to start. Check your .env against "
            f".env.example. Original error: {e}"
        ) from e
