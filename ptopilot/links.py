"""Signed tokens for sign-in links and one-click tracker actions (snooze buttons in the digest).

Shared by the digest job and the web app, so both must use the same SECRET_KEY. No web imports here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

LOGIN_MAX_AGE_S = 15 * 60
ACTION_MAX_AGE_S = 30 * 24 * 3600

ACTION_LABELS = {
    "trip": "Not this trip",
    "snooze30": "Snooze 30 days",
    "year": "Not this year",
    "under": "Only if under $…",
}


class TokenError(Exception):
    """A token that is malformed, tampered with, or expired."""


def _serializer(secret: str, salt: str) -> URLSafeTimedSerializer:
    if not secret:
        raise ValueError("SECRET_KEY is not set")
    return URLSafeTimedSerializer(secret, salt=salt)


def _read(secret: str, salt: str, token: str, max_age: int):
    try:
        return _serializer(secret, salt).loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise TokenError("this link has expired") from exc
    except BadSignature as exc:
        raise TokenError("this link is not valid") from exc


def login_token(secret: str, email: str) -> str:
    return _serializer(secret, "login").dumps(email.strip().lower())


def read_login_token(secret: str, token: str, max_age: int = LOGIN_MAX_AGE_S) -> str:
    return _read(secret, "login", token, max_age)


@dataclass(frozen=True)
class Action:
    tracker_id: int
    kind: str  # one of ACTION_LABELS
    depart: date | None = None  # the trip the link was attached to
    ret: date | None = None


def action_token(secret: str, action: Action) -> str:
    payload = {"t": action.tracker_id, "a": action.kind}
    if action.depart and action.ret:
        payload |= {"d": action.depart.isoformat(), "r": action.ret.isoformat()}
    return _serializer(secret, "action").dumps(payload)


def read_action_token(secret: str, token: str, max_age: int = ACTION_MAX_AGE_S) -> Action:
    data = _read(secret, "action", token, max_age)
    if not isinstance(data, dict) or data.get("a") not in ACTION_LABELS or not isinstance(data.get("t"), int):
        raise TokenError("this link is not valid")
    depart = date.fromisoformat(data["d"]) if data.get("d") else None
    ret = date.fromisoformat(data["r"]) if data.get("r") else None
    return Action(data["t"], data["a"], depart, ret)


def action_links(
    base_url: str, secret: str, tracker_id: int, depart: date, ret: date
) -> list[tuple[str, str]]:
    """(label, url) for each snooze button on a deal card."""
    return [
        (label, f"{base_url}/s/{action_token(secret, Action(tracker_id, kind, depart, ret))}")
        for kind, label in ACTION_LABELS.items()
    ]
