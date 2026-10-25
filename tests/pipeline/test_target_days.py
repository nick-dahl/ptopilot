"""A destination's target length drives planning (target +/- 2 days away) and scoring."""

from datetime import date

from sqlalchemy import select

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.planner import TrackerSpec, TravelerProfile, Window, plan_itineraries
from ptopilot.db.models import Candidate, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, score
from tests.pipeline.conftest import GEO, RUN, SEASONS, add_observation, add_tracker, add_user

JUNE = [Window(date(2027, 6, 1), date(2027, 6, 30))]
THANKSGIVING = [Window(date(2027, 10, 28), date(2027, 11, 30))]  # the only stretch with 7-day shapes
TRIP = (date(2027, 6, 12), date(2027, 6, 20))  # 9 days away


def link_days(engine, tracker_id) -> list[int]:
    with session_scope(engine) as s:
        return [lk.days_away for lk in s.scalars(select(TrackerRouteLink).filter_by(tracker_id=tracker_id))]


def test_a_target_of_11_plans_only_9_to_13_days_away(make_ctx):
    ctx = make_ctx()
    tid = add_tracker(ctx.engine, add_user(ctx.engine), min_stay=1, max_stay=30, target_days=11)
    expand.run(ctx)
    days = link_days(ctx.engine, tid)
    assert days
    assert all(9 <= d <= 13 for d in days)


def test_target_below_the_routes_minimum_starts_at_the_minimum():
    calendar = WorkCalendar.from_code("US", [], [])
    profile = TravelerProfile(("JFK",), calendar, 15, 5, 16)
    spec = TrackerSpec("TYO", 1, 30, target_days=5)
    planned = plan_itineraries(profile, spec, THANKSGIVING, GEO, SEASONS)
    assert planned  # target 5 -> 3..7, clamped up to the route's 7-day minimum -> exactly 7
    assert all(it.shape.days_away >= 7 for it in planned)


def test_without_a_target_planning_is_unchanged(make_ctx):
    ctx = make_ctx()
    tid = add_tracker(ctx.engine, add_user(ctx.engine), target_days=None)
    counts = expand.run(ctx)
    assert counts == {"trackers": 1, "links": 6, "route_queries": 6}  # same as test_expand's baseline
    assert 9 in link_days(ctx.engine, tid)


def test_go_now_prefers_the_trackers_target_over_the_users_ideal(make_ctx):
    ctx = make_ctx()
    targeted = add_tracker(
        ctx.engine, add_user(ctx.engine, "a@example.com", ideal_trip_days=15), target_days=9
    )
    plain = add_tracker(ctx.engine, add_user(ctx.engine, "b@example.com", ideal_trip_days=15))
    expand.run(ctx)
    add_observation(ctx.engine, *TRIP, 820, observed=RUN, verified=True, stops=1, duration_min=780)
    score.run(ctx)
    with session_scope(ctx.engine) as s:
        rows = s.scalars(select(Candidate).where(Candidate.evening_departure.is_(False)))
        go = {c.tracker_id: c.go_now for c in rows}
    assert go[targeted] - go[plain] in (9, 10, 11)  # the length weight (0.1), up to rounding
