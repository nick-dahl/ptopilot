"""Choosing and publishing each person's weekly hidden gem (Plan 16, spec section 3.4)."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.core.geo import Geo, UnknownCodeError
from ptopilot.db.models import GemIssue, Tracker, User
from ptopilot.gems import Gem, approved


def next_gem(
    gems: Sequence[Gem],
    issued: Sequence[str],
    styles: Sequence[str],
    tracked_airports: Collection[str],
    issue_number: int,
) -> Gem | None:
    """The next gem for someone: the approved, unissued, untracked gem best matching their styles.

    Every GEM_WILDCARD_EVERY-th issue (1-based), or anyone with no styles, gets the first candidate in
    catalogue order instead; ties go to catalogue order."""
    tracked = set(tracked_airports)
    done = set(issued)
    candidates = [
        g for g in approved(gems) if g.slug not in done and tracked.isdisjoint(g.airports + g.return_airports)
    ]
    if not candidates:
        return None
    if not styles or issue_number % config.GEM_WILDCARD_EVERY == 0:
        return candidates[0]
    wanted = set(styles)
    return max(candidates, key=lambda g: len(wanted.intersection(g.styles)))  # max keeps the first of ties


def tracked_airports(s: Session, user: User, geo: Geo) -> set[str]:
    """Every airport belonging to the destinations of the person's active trackers."""
    codes = s.scalars(select(Tracker.destination_code).where(Tracker.user_id == user.id, Tracker.active))
    airports: set[str] = set()
    for code in codes:
        try:
            airports.update(geo.destination(code).own_airports)
        except UnknownCodeError:
            continue  # a place no longer known excludes nothing
    return airports


def publish_due(
    s: Session, user: User, today: date, gems: Sequence[Gem], geo: Geo | None = None
) -> GemIssue | None:
    """Publish the person's next gem if their latest issue is GEM_ISSUE_DAYS old (or they have none).

    Idempotent: a repeat or concurrent call inserts nothing (unique on user and gem)."""
    issues = s.execute(
        select(GemIssue.gem_slug, GemIssue.published_on).where(GemIssue.user_id == user.id)
    ).all()
    if issues and today - max(p for _, p in issues) < timedelta(days=config.GEM_ISSUE_DAYS):
        return None
    if geo is None:
        from ptopilot.data import load_geo

        geo = load_geo(s.get_bind())
    gem = next_gem(
        gems,
        [slug for slug, _ in issues],
        user.trip_styles,
        tracked_airports(s, user, geo),
        len(issues) + 1,
    )
    if gem is None:
        return None
    new_id = s.execute(
        insert(GemIssue)
        .values(user_id=user.id, gem_slug=gem.slug, published_on=today)
        .on_conflict_do_nothing(index_elements=["user_id", "gem_slug"])
        .returning(GemIssue.id)
    ).scalar_one_or_none()
    return None if new_id is None else s.get(GemIssue, new_id)
