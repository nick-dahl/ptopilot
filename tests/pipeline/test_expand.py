from datetime import date

from sqlalchemy import func, select

from ptopilot.db.models import RouteQuery, TrackerExclusion, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand
from tests.pipeline.conftest import RUN, add_tracker, add_user

JUNETEENTH_TRIP = (date(2027, 6, 12), date(2027, 6, 20))


def links(engine, tracker_id=None):
    with session_scope(engine) as s:
        q = select(TrackerRouteLink, RouteQuery).join(RouteQuery)
        if tracker_id is not None:
            q = q.where(TrackerRouteLink.tracker_id == tracker_id)
        return [
            (rq.origin, rq.dest_airport, rq.depart_date, rq.return_date, link)
            for link, rq in s.execute(q).all()
        ]


def count(engine, model):
    with session_scope(engine) as s:
        return s.scalar(select(func.count()).select_from(model))


def test_builds_links_and_route_queries_for_an_active_tracker(make_ctx):
    ctx = make_ctx()
    tid = add_tracker(ctx.engine, add_user(ctx.engine))
    counts = expand.run(ctx)
    assert counts == {"trackers": 1, "links": 6, "route_queries": 6}
    rows = links(ctx.engine, tid)
    assert {(o, d) for o, d, *_ in rows} == {("ORD", "LIS")}
    assert (*JUNETEENTH_TRIP,) in {(dep, ret) for _, _, dep, ret, _ in rows}
    link = next(lk for _, _, dep, ret, lk in rows if (dep, ret) == JUNETEENTH_TRIP)
    assert (link.pto_cost, link.days_away, link.season_rating) == (4, 9, "good")
    assert link.days_off == ["Juneteenth National Independence Day (observed)"]


def test_rerun_is_idempotent(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    expand.run(ctx)
    assert count(ctx.engine, TrackerRouteLink) == 6
    assert count(ctx.engine, RouteQuery) == 6


def test_two_users_share_route_queries(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine, "a@example.com"))
    add_tracker(ctx.engine, add_user(ctx.engine, "b@example.com"))
    counts = expand.run(ctx)
    assert (counts["links"], counts["route_queries"]) == (12, 6)
    assert count(ctx.engine, RouteQuery) == 6


def test_snoozed_and_inactive_trackers_are_skipped(make_ctx):
    ctx = make_ctx()
    uid = add_user(ctx.engine)
    add_tracker(ctx.engine, uid, "PRG", snoozed_until=RUN)
    add_tracker(ctx.engine, uid, "ATH", active=False)
    expired = add_tracker(ctx.engine, uid, snoozed_until=date(2027, 2, 28))
    assert expand.run(ctx)["trackers"] == 1
    assert {lk.tracker_id for *_, lk in links(ctx.engine)} == {expired}


def test_excluded_trip_is_not_linked(make_ctx):
    ctx = make_ctx()
    tid = add_tracker(ctx.engine, add_user(ctx.engine))
    with session_scope(ctx.engine) as s:
        s.add(
            TrackerExclusion(tracker_id=tid, depart_date=JUNETEENTH_TRIP[0], return_date=JUNETEENTH_TRIP[1])
        )
    counts = expand.run(ctx)
    assert counts["excluded"] == 1
    assert JUNETEENTH_TRIP not in {(dep, ret) for _, _, dep, ret, _ in links(ctx.engine)}


def test_never_plans_departures_on_or_before_the_run_date(make_ctx):
    ctx = make_ctx(run_date=date(2027, 6, 10))
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    assert all(dep > date(2027, 6, 10) for _, _, dep, _, _ in links(ctx.engine))


def test_users_whose_windows_are_all_past_are_counted(make_ctx):
    ctx = make_ctx(run_date=date(2027, 7, 1))
    add_tracker(ctx.engine, add_user(ctx.engine))
    assert expand.run(ctx) == {"trackers": 1, "trackers_without_windows": 1, "route_queries": 0}


def test_a_bad_tracker_does_not_stop_the_others(make_ctx):
    ctx = make_ctx()
    uid = add_user(ctx.engine)
    add_tracker(ctx.engine, uid, code="ZZZ")
    good = add_tracker(ctx.engine, uid)
    counts = expand.run(ctx)
    assert counts["tracker_errors"] == 1
    assert {lk.tracker_id for *_, lk in links(ctx.engine)} == {good}
