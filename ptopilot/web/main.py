"""ASGI entry point for the server: `uvicorn ptopilot.web.main:app`. Reads settings from the environment."""

import os
from collections.abc import Mapping

from ptopilot.settings import Settings
from ptopilot.web.app import create_app


def check_production(settings: Settings, env: Mapping[str, str]) -> None:
    """Refuse to start on Render without an https base URL: the session cookie's secure flag follows it."""
    if env.get("RENDER") and not settings.app_base_url.startswith("https://"):
        raise SystemExit("APP_BASE_URL must be the site's https:// URL in production")


def __getattr__(name: str):
    """Build `app` on first access, so importing this module (for tests) needs no environment."""
    if name != "app":
        raise AttributeError(name)
    settings = Settings.from_env()
    check_production(settings, os.environ)
    globals()["app"] = created = create_app(settings)
    return created
