"""The preferred trip length flows from the user into planning (which trips get priced) and scoring."""

from datetime import date

from sqlalchemy import select

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.planner import TrackerSpec, TravelerProfile, Window, plan_itineraries
from ptopilot.db.models import Candidate, User
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, score
from ptopilot.pipeline.expand import profile_for
from tests.pipeline.conftest import GEO, RUN, SEASONS, add_observation, add_tracker, add_user

JUNE = [Window(date(2027, 6, 1), date(2027, 6, 30))]
TRIP = (date(2027, 6, 12), date(2027, 6, 20))  # 9 days away


def profile(ideal=None) -> TravelerProfile:
    calendar = WorkCalendar.from_code("US", [], [])
    return TravelerProfile(("JFK",), calendar, 15, 7, 16, ideal_trip_days=ideal)


def lengths(ideal) -> list[int]:
    picked = plan_itineraries(profile(ideal), TrackerSpec("AZORES", 5, 14), JUNE, GEO, SEASONS, top_n=4)
    return sorted(it.shape.days_away for it in picked)


def test_profile_carries_the_users_ideal_length():
    user = User(
        home_airport="JFK",
        nearby_airports=[],
        holiday_calendar="US",
        extra_days_off=[],
        ignored_holidays=[],
        pto_days_total=15,
        pto_committed=0,
        min_trip_days=7,
        max_trip_days=16,
        ideal_trip_days=12,
        weather_tolerance="normal",
        friday_evening_departure=False,
    )
    assert profile_for(user).ideal_trip_days == 12


def test_no_preference_plans_exactly_as_before():
    assert lengths(None) == [9, 10, 10, 11]  # by PTO efficiency alone (Juneteenth makes 9 days cost 4)


def test_planner_prices_a_trip_near_the_ideal_ahead_of_a_slightly_more_efficient_one():
    # June offers 9-, 10-, 11- and 16-day weekend-to-weekend trips. With a 14-day ideal the 16-day trip
    # (fit 0.5) takes the 11-day trip's slot; the far more efficient Juneteenth trips keep theirs.
    assert lengths(14) == [9, 10, 10, 16]


def test_go_now_rewards_the_trip_matching_the_ideal(make_ctx):
    ctx = make_ctx()
    match = add_tracker(ctx.engine, add_user(ctx.engine, "a@example.com", ideal_trip_days=9))
    far = add_tracker(ctx.engine, add_user(ctx.engine, "b@example.com", ideal_trip_days=15))
    expand.run(ctx)
    add_observation(ctx.engine, *TRIP, 820, observed=RUN, verified=True, stops=1, duration_min=780)
    score.run(ctx)
    with session_scope(ctx.engine) as s:
        rows = s.scalars(select(Candidate).where(Candidate.evening_departure.is_(False)))
        go = {c.tracker_id: c.go_now for c in rows}
    assert go[match] - go[far] in (9, 10, 11)  # the length weight (0.1), up to rounding
