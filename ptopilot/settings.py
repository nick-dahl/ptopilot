"""Runtime settings from environment variables. Secrets never live in the repo."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEV_DATABASE_URL = "postgresql+psycopg://ptopilot@localhost:5433/ptopilot"


def normalize_database_url(url: str) -> str:
    """Neon and most hosts give postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str
    travelpayouts_token: str = ""
    serpapi_key: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        return cls(
            database_url=normalize_database_url(env.get("DATABASE_URL") or DEV_DATABASE_URL),
            travelpayouts_token=env.get("TRAVELPAYOUTS_TOKEN", ""),
            serpapi_key=env.get("SERPAPI_KEY", ""),
        )
