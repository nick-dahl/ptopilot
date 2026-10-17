"""Outbound email through Resend's HTTP API."""

from __future__ import annotations

import re
from typing import Protocol

import httpx

from ptopilot.sources.base import snippet

API_URL = "https://api.resend.com/emails"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
TIMEOUT_S = 20


class EmailError(Exception):
    """A failed send. Messages never contain email addresses: they end up in public CI logs."""

    def __init__(self, message: str):
        super().__init__(EMAIL_RE.sub("<email>", message))


class Emailer(Protocol):
    def send(self, to: str, subject: str, html: str, text: str) -> str: ...


class ResendEmailer:
    def __init__(self, api_key: str, sender: str, client: httpx.Client | None = None):
        if not api_key:
            raise ValueError("Resend API key is empty; set RESEND_API_KEY")
        self._key = api_key
        self._sender = sender
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def send(self, to: str, subject: str, html: str, text: str) -> str:
        """Send one email; returns Resend's message id."""
        body = {"from": self._sender, "to": [to], "subject": subject, "html": html, "text": text}
        try:
            resp = self._client.post(API_URL, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as exc:
            raise EmailError(f"resend: {type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 300:
            raise EmailError(f"resend: HTTP {resp.status_code}: {snippet(resp.text)}")
        return str(resp.json().get("id", ""))
