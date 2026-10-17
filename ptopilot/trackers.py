"""Tracker actions shared by the dashboard and the digest's snooze links."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ptopilot.db.models import Tracker, TrackerExclusion
from ptopilot.links import Action


def snooze(tracker: Tracker, until: date) -> None:
    tracker.snoozed_until = until


def unsnooze(tracker: Tracker) -> None:
    tracker.snoozed_until = None


def exclude_trip(s: Session, tracker: Tracker, depart: date, ret: date) -> None:
    s.execute(
        insert(TrackerExclusion)
        .values(tracker_id=tracker.id, depart_date=depart, return_date=ret)
        .on_conflict_do_nothing()
    )


def apply_action(
    s: Session, tracker: Tracker, action: Action, today: date, price: Decimal | None = None
) -> str:
    """Apply a snooze-link action; returns a sentence describing what happened."""
    if action.kind == "trip":
        if not (action.depart and action.ret):
            raise ValueError("this link has no trip attached")
        exclude_trip(s, tracker, action.depart, action.ret)
        trip = f"{action.depart:%b} {action.depart.day} → {action.ret:%b} {action.ret.day}"
        return f"Got it: {trip} won't be suggested again."
    if action.kind == "snooze30":
        until = today + timedelta(days=30)
        snooze(tracker, until)
        return f"Snoozed until {until:%b} {until.day}, {until.year}."
    if action.kind == "year":
        year = action.depart.year if action.depart else today.year
        snooze(tracker, date(year, 12, 31))
        return f"Snoozed for the rest of {year}."
    if action.kind == "under":
        if price is None or price <= 0:
            raise ValueError("enter a price above zero")
        tracker.max_price = price
        return f"You'll only hear about this destination under ${price:,.0f}."
    raise ValueError(f"unknown action {action.kind!r}")
