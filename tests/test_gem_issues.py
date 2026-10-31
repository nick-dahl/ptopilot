from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, select

from ptopilot.core.gem_feed import publish_due, tracked_airports
from ptopilot.data import load_geo
from ptopilot.db.models import GemIssue, Tracker
from ptopilot.gems import load_catalogue
from tests.db.test_models import make_user

FIXTURES = Path(__file__).parent / "fixtures" / "gems"
TODAY = date(2026, 11, 1)


def count(session, user):
    return session.scalar(select(func.count()).select_from(GemIssue).where(GemIssue.user_id == user.id))


def test_publish_due_waits_seven_days(session):
    gems = load_catalogue(FIXTURES)
    user = make_user(session)
    session.add(GemIssue(user_id=user.id, gem_slug="lipnica-valley", published_on=TODAY - timedelta(days=6)))
    session.flush()
    assert publish_due(session, user, TODAY, gems) is None
    issue = publish_due(session, user, TODAY + timedelta(days=1), gems)
    assert issue is not None and issue.gem_slug == "hoegvik-islands"
    assert issue.published_on == TODAY + timedelta(days=1)


def test_publish_due_is_idempotent(session):
    gems = load_catalogue(FIXTURES)
    user = make_user(session)
    first = publish_due(session, user, TODAY, gems)
    assert first is not None
    assert publish_due(session, user, TODAY, gems) is None
    assert count(session, user) == 1


def test_catalogue_exhausted_publishes_nothing(session):
    gems = load_catalogue(FIXTURES)
    user = make_user(session)
    day = TODAY
    for _ in range(2):  # the two approved fixture gems
        assert publish_due(session, user, day, gems) is not None
        day += timedelta(days=7)
    assert publish_due(session, user, day, gems) is None
    assert count(session, user) == 2


def test_tracked_places_are_skipped_when_publishing(session):
    user = make_user(session)
    session.add(Tracker(user_id=user.id, destination_code="TH", min_stay_days=7, max_stay_days=12))
    session.add(
        Tracker(user_id=user.id, destination_code="JP", min_stay_days=7, max_stay_days=12, active=False)
    )
    session.flush()
    geo = load_geo(session.get_bind())
    th = set(geo.destination("TH").own_airports)
    assert tracked_airports(session, user, geo) == th
    first, second = [g for g in load_catalogue(FIXTURES) if g.status == "approved"]
    gems = [replace(first, airports=tuple(sorted(th))), second]
    assert publish_due(session, user, TODAY, gems, geo).gem_slug == second.slug
