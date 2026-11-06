from datetime import UTC, date, datetime

from ptopilot.db.models import LiveCheck, RouteQuery, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.pipeline import freshness, live_verify
from ptopilot.sources.base import SourceUnavailable
from tests.pipeline.conftest import FakeLiveSource, add_tracker, add_user, failing

DAY = date(2026, 11, 5)


def at(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def add_rq(engine, tracker_id, depart=date(2026, 12, 10), dest="LIS", ret_airport=None, link_day=DAY):
    with session_scope(engine) as s:
        rq = RouteQuery(
            origin="ORD",
            dest_airport=dest,
            return_airport=ret_airport or dest,
            depart_date=depart,
            return_date=date(depart.year, depart.month, depart.day + 6),
        )
        s.add(rq)
        s.flush()
        s.add(
            TrackerRouteLink(
                tracker_id=tracker_id,
                route_query_id=rq.id,
                run_date=link_day,
                pto_cost=3,
                month=12,
                season_rating="ok",
                days_away=7,
                efficiency=1.0,
            )
        )
        return rq.id


def check(engine, rq_id, ok=True, source="google_flights", options=1, day=DAY, route_specific=False, hour=9):
    with session_scope(engine) as s:
        s.add(
            LiveCheck(
                run_date=day,
                route_query_id=rq_id,
                source=source,
                ok=ok,
                options=options,
                error=None if ok else "boom",
                checked_at=at(day, hour),
                route_specific=route_specific,
            )
        )


def setup(clean_engine):
    return add_tracker(clean_engine, add_user(clean_engine))


def test_ok_no_flights_and_serpapi_count_as_fresh(clean_engine):
    t = setup(clean_engine)
    a, b, c = (add_rq(clean_engine, t, depart=date(2026, 12, d)) for d in (10, 11, 12))
    check(clean_engine, a, options=0)
    check(clean_engine, b, source="serpapi")
    check(clean_engine, c, ok=False)
    with session_scope(clean_engine) as s:
        assert freshness.fresh_on(s, DAY) == {a, b}
        assert freshness.google_fresh_on(s, DAY) == {a}


def test_last_fresh_ignores_failures_and_respects_before(clean_engine):
    t = setup(clean_engine)
    a = add_rq(clean_engine, t)
    check(clean_engine, a, day=date(2026, 11, 1))
    check(clean_engine, a, day=date(2026, 11, 3))
    check(clean_engine, a, ok=False, day=date(2026, 11, 4))
    with session_scope(clean_engine) as s:
        assert freshness.last_fresh(s, [a]) == {a: at(date(2026, 11, 3))}
        assert freshness.last_fresh(s, [a], before=at(date(2026, 11, 2))) == {a: at(date(2026, 11, 1))}
        assert freshness.last_fresh(s, [a], before=at(date(2026, 11, 1), 1)) == {}


def test_day_freshness_splits_unpriceable_and_open_jaw(clean_engine):
    t = setup(clean_engine)
    fresh = add_rq(clean_engine, t, depart=date(2026, 12, 10))
    unpriceable = add_rq(clean_engine, t, depart=date(2026, 12, 11))
    open_jaw = add_rq(clean_engine, t, depart=date(2026, 12, 12), ret_airport="OPO")
    stale = add_rq(clean_engine, t, depart=date(2026, 12, 13))
    check(clean_engine, fresh)
    check(clean_engine, unpriceable, ok=False, route_specific=True, hour=9)
    check(clean_engine, unpriceable, ok=False, route_specific=True, source="serpapi", hour=10)
    check(clean_engine, stale, ok=False)
    with session_scope(clean_engine) as s:
        got = freshness.day_freshness(s, DAY)
    assert (got.in_horizon, got.fresh) == (4, 1)
    assert got.not_fresh == [stale]
    assert got.unpriceable == [unpriceable]
    assert got.open_jaw_no_budget == [open_jaw]


def test_out_of_horizon_routes_are_not_counted(clean_engine):
    t = setup(clean_engine)
    add_rq(clean_engine, t, depart=date(2027, 12, 1))
    with session_scope(clean_engine) as s:
        assert freshness.day_freshness(s, DAY).in_horizon == 0


def test_longest_wait_counts_days_since_last_fresh(clean_engine):
    t = setup(clean_engine)
    a = add_rq(clean_engine, t)
    check(clean_engine, a, day=date(2026, 11, 2))
    check(clean_engine, a, ok=False)
    with session_scope(clean_engine) as s:
        assert freshness.day_freshness(s, DAY).longest_wait_days == 3


def test_never_fresh_waits_since_first_link(clean_engine):
    t = setup(clean_engine)
    a = add_rq(clean_engine, t, link_day=date(2026, 11, 1))
    with session_scope(clean_engine) as s:
        s.add(
            TrackerRouteLink(
                tracker_id=t,
                route_query_id=a,
                run_date=DAY,
                pto_cost=3,
                days_away=7,
                efficiency=1.0,
                month=12,
                season_rating="ok",
            )
        )
    with session_scope(clean_engine) as s:
        assert freshness.day_freshness(s, DAY).longest_wait_days == 4


def test_route_specific_failures_are_recorded(make_ctx):
    from ptopilot.pipeline import expand, shortlist

    def respond(q):
        raise SourceUnavailable("unreadable page", route_specific=True)

    ctx = make_ctx(live_sources=[FakeLiveSource("google_flights", respond)])
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    shortlist.run(ctx)
    try:
        live_verify.run(ctx)
    except Exception:
        pass
    with session_scope(ctx.engine) as s:
        rows = list(s.query(LiveCheck))
    assert rows and all(r.route_specific is True and not r.ok for r in rows)


def test_plain_failures_are_not_route_specific(make_ctx):
    from ptopilot.pipeline import expand, shortlist

    ctx = make_ctx(live_sources=[FakeLiveSource("google_flights", failing())])
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    shortlist.run(ctx)
    try:
        live_verify.run(ctx)
    except Exception:
        pass
    with session_scope(ctx.engine) as s:
        assert all(r.route_specific is False for r in s.query(LiveCheck))
