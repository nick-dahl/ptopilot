"""Standout offers: a great, verified deal that is likely to vanish within days (pure, no I/O)."""

from __future__ import annotations

from ptopilot import config
from ptopilot.core.duration import duration_label


def is_standout(
    go_now: int, deal_level: str, confidence: str, verified: bool, expected_days: int | None
) -> bool:
    return (
        go_now >= config.STANDOUT_GO_NOW
        and deal_level == "great"
        and confidence == "normal"
        and verified
        and expected_days is not None
        and expected_days <= config.STANDOUT_MAX_DAYS
    )


def standout_tag(expected_days: int | None) -> str | None:
    """ "Rare: likely gone within ~2 days" for a standout offer."""
    label = duration_label(expected_days)
    return f"Rare: {label}" if label else None
