"""Runtime settings from environment variables. Secrets never live in the repo."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEV_DATABASE_URL = "postgresql+psycopg://ptopilot@localhost:5433/ptopilot"
# Resend's shared sender; without a verified domain it can only deliver to the Resend account's own address.
DEFAULT_EMAIL_FROM = "ptopilot <onboarding@resend.dev>"


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
    resend_api_key: str = ""
    admin_email: str = ""
    email_from: str = DEFAULT_EMAIL_FROM
    secret_key: str = (
        ""  # signs sign-in links, sessions and snooze links; shared by the web app and the digest job
    )
    app_base_url: str = (
        ""  # public URL of the web app, e.g. https://ptopilot.onrender.com; enables snooze links
    )

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        return cls(
            database_url=normalize_database_url(env.get("DATABASE_URL") or DEV_DATABASE_URL),
            travelpayouts_token=env.get("TRAVELPAYOUTS_TOKEN", ""),
            serpapi_key=env.get("SERPAPI_KEY", ""),
            resend_api_key=env.get("RESEND_API_KEY", ""),
            admin_email=env.get("ADMIN_EMAIL", ""),
            email_from=env.get("EMAIL_FROM") or DEFAULT_EMAIL_FROM,
            secret_key=env.get("SECRET_KEY", ""),
            app_base_url=(env.get("APP_BASE_URL") or "").rstrip("/"),
        )
