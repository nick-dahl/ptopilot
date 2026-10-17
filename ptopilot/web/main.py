"""ASGI entry point for the server: `uvicorn ptopilot.web.main:app`. Reads settings from the environment."""

from ptopilot.settings import Settings
from ptopilot.web.app import create_app

app = create_app(Settings.from_env())
