from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import LiveCheck, RouteBaseline, RouteQuery, ShortlistEntry, TrackerRouteLink
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, shortlist
from tests.pipeline.conftest import (
    RUN,
    FakeLiveSource,
    add_live_check,
    add_observation,
    add_tracker,
    add_user,
    answering,
    option,
)

JUNE = date(2027, 6, 1)
DEAL = (date(2027, 6, 12), date(2027, 6, 20))  # 9 days away -> "week" bucket
PRICEY = (date(2027, 6, 11), date(2027, 6, 20))  # 10 days away -> "week" bucket
LATE = (date(2027, 6, 17), date(2027, 6, 27))  # 11 days away -> "long"; created after the others


def entries(engine):
    with session_scope(engine) as s:
        rows = s.execute(
            select(ShortlistEntry, RouteQuery).join(RouteQuery).order_by(ShortlistEntry.rank)
        ).all()
        return [(e.rank, e.reason, (rq.depart_date, rq.return_date), e.est_price) for e, rq in rows]


def confident_baseline(engine, bucket="week", median=1000, sigma=100):
    with session_scope(engine) as s:
        s.add(
            RouteBaseline(
                origin="ORD",
                dest_airport="LIS",
                return_airport="LIS",
                month=JUNE,
                length_bucket=bucket,
                median=Decimal(median),
                sigma=Decimal(sigma),
                n=20,
                confidence="normal",
            )
        )


def setup(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    return ctx


def test_without_history_everything_is_exploration(make_ctx):
    ctx = setup(make_ctx)
    counts = shortlist.run(ctx)
    assert counts["explore"] == 6 and counts["deal"] == 0
    assert all(reason == "explore" for _, reason, _, _ in entries(ctx.engine))


def test_cheap_cached_price_against_confident_baseline_is_a_deal(make_ctx):
    ctx = setup(make_ctx)
    confident_baseline(ctx.engine)
    confident_baseline(ctx.engine, bucket="long")
    add_observation(ctx.engine, *DEAL, 800, observed=RUN)  # z = -2
    add_observation(ctx.engine, *PRICEY, 990, observed=RUN)  # z = -0.1
    counts = shortlist.run(ctx)
    # DEAL's own fare, plus 4 routes with no exact fare estimated from June's cheapest ($800)
    assert (counts["deal"], counts["not_cheap"]) == (5, 1)
    assert entries(ctx.engine)[0][:2] == (1, "deal")


def test_exact_date_fare_outranks_month_level_estimates(make_ctx):
    ctx = setup(make_ctx)
    confident_baseline(ctx.engine)
    confident_baseline(ctx.engine, bucket="long")
    add_observation(ctx.engine, *LATE, 800, observed=RUN)  # exact fare; also June's cheapest
    shortlist.run(ctx)
    first = entries(ctx.engine)[0]
    assert first[:3] == (1, "deal", LATE)
    assert first[3] == 800


def test_stale_cached_prices_are_ignored(make_ctx):
    ctx = setup(make_ctx)
    confident_baseline(ctx.engine)
    add_observation(ctx.engine, *DEAL, 800, observed=date(2027, 2, 20))  # older than CACHE_LOOKBACK_DAYS
    shortlist.run(ctx)
    assert "deal" not in {reason for _, reason, _, _ in entries(ctx.engine)}


def test_exploration_prefers_routes_never_checked_live(make_ctx):
    ctx = setup(make_ctx)
    add_live_check(ctx.engine, *DEAL, run_date=date(2027, 2, 1), ok=True)
    shortlist.run(ctx)
    assert entries(ctx.engine)[-1][2] == DEAL


def test_a_no_flights_check_still_counts_as_checked(make_ctx):
    ctx = setup(make_ctx)
    add_live_check(ctx.engine, *DEAL, run_date=date(2027, 2, 1), ok=True)  # stored no price rows
    shortlist.run(ctx)
    assert entries(ctx.engine)[-1][2] == DEAL


def test_departures_beyond_the_search_horizon_are_skipped(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "LIVE_HORIZON_DAYS", 100)  # run 2027-03-01 -> June trips are ~100+ days out
    ctx = setup(make_ctx)
    counts = shortlist.run(ctx)
    assert counts["beyond_horizon"] >= 1
    assert all((dep - RUN).days <= 100 for _, _, (dep, _), _ in entries(ctx.engine))


def test_rerun_replaces_the_days_shortlist(make_ctx):
    ctx = setup(make_ctx)
    shortlist.run(ctx)
    shortlist.run(ctx)
    assert [rank for rank, *_ in entries(ctx.engine)] == [1, 2, 3, 4, 5, 6]


def test_same_day_rerun_keeps_the_not_yet_fresh_trips_in_the_same_order(make_ctx):
    ctx = setup(make_ctx)
    shortlist.run(ctx)
    first = [dates for _, _, dates, _ in entries(ctx.engine)]
    for dep, ret in first[:3]:  # live_verify checked the first three earlier today
        add_live_check(ctx.engine, dep, ret, run_date=RUN)
    shortlist.run(ctx)
    # fresh trips drop out (cold, far away); the rest keep their order since staleness ignores today's checks
    assert [dates for _, _, dates, _ in entries(ctx.engine)] == first[3:]


# --- Plan 18: every in-horizon trip, in check order ---------------------------------------------------------


def make_rq(engine, tracker_id, depart, ret, dest="LIS", return_airport=None) -> int:
    with session_scope(engine) as s:
        rq = RouteQuery(
            origin="ORD",
            dest_airport=dest,
            return_airport=return_airport or dest,
            depart_date=depart,
            return_date=ret,
        )
        s.add(rq)
        s.flush()
        s.add(
            TrackerRouteLink(
                tracker_id=tracker_id,
                route_query_id=rq.id,
                run_date=RUN,
                pto_cost=3,
                days_away=9,
                efficiency=1.0,
                month=depart.month,
                season_rating="good",
            )
        )
        return rq.id


def check(engine, rq_id, run_date, at, source="google_flights", ok=True):
    with session_scope(engine) as s:
        s.add(LiveCheck(run_date=run_date, route_query_id=rq_id, source=source, ok=ok, checked_at=at))


def fresh_today(engine, rq_id, source="google_flights"):
    check(engine, rq_id, RUN, datetime(2027, 3, 1, 6, tzinfo=UTC), source)


def ids_in_order(engine):
    with session_scope(engine) as s:
        rows = s.execute(select(ShortlistEntry).order_by(ShortlistEntry.rank)).scalars()
        return [(e.route_query_id, e.reason) for e in rows]


def bare(make_ctx, **fields):
    ctx = make_ctx(**fields)
    return ctx, add_tracker(ctx.engine, add_user(ctx.engine))


def test_every_in_horizon_trip_is_shortlisted(make_ctx):
    ctx, tid = bare(make_ctx)
    for i in range(200):
        make_rq(ctx.engine, tid, RUN + timedelta(days=10 + i), RUN + timedelta(days=18 + i))
    make_rq(ctx.engine, tid, RUN + timedelta(days=400), RUN + timedelta(days=408))
    counts = shortlist.run(ctx)
    got = ids_in_order(ctx.engine)
    assert len(got) == 200 and all(reason != "second" for _, reason in got)
    assert counts["beyond_horizon"] == 1


def test_longest_waiting_goes_first(make_ctx):
    ctx, tid = bare(make_ctx)
    three = make_rq(ctx.engine, tid, date(2027, 5, 1), date(2027, 5, 9))
    one = make_rq(ctx.engine, tid, date(2027, 5, 2), date(2027, 5, 10))
    never = make_rq(ctx.engine, tid, date(2027, 5, 3), date(2027, 5, 11))
    check(ctx.engine, three, date(2027, 2, 26), datetime(2027, 2, 26, 12, tzinfo=UTC))
    check(ctx.engine, one, date(2027, 2, 28), datetime(2027, 2, 28, 12, tzinfo=UTC))
    shortlist.run(ctx)
    assert [i for i, _ in ids_in_order(ctx.engine)] == [never, three, one]


def test_promise_breaks_ties_within_the_same_wait(make_ctx):
    ctx, tid = bare(make_ctx)
    plain = make_rq(ctx.engine, tid, date(2027, 5, 20), date(2027, 5, 28))  # departs first, no signal
    deal = make_rq(ctx.engine, tid, *DEAL)
    for rq_id in (plain, deal):
        check(ctx.engine, rq_id, date(2027, 2, 28), datetime(2027, 2, 28, 12, tzinfo=UTC))
    confident_baseline(ctx.engine)
    add_observation(ctx.engine, *DEAL, 800, observed=RUN)  # z = -2
    shortlist.run(ctx)
    assert ids_in_order(ctx.engine) == [(deal, "deal"), (plain, "explore")]


def test_fresh_today_goes_after_every_not_fresh_trip(make_ctx):
    ctx, tid = bare(make_ctx)
    soon = make_rq(ctx.engine, tid, RUN + timedelta(days=10), RUN + timedelta(days=18))  # hot: departs soon
    waiting = [make_rq(ctx.engine, tid, date(2027, 7, d), date(2027, 7, d + 8)) for d in (1, 2)]
    fresh_today(ctx.engine, soon)
    shortlist.run(ctx)
    assert ids_in_order(ctx.engine) == [(waiting[0], "explore"), (waiting[1], "explore"), (soon, "second")]


def test_staleness_ignores_todays_own_checks(make_ctx):
    ctx, tid = bare(make_ctx)
    a = make_rq(ctx.engine, tid, date(2027, 7, 1), date(2027, 7, 9))
    b = make_rq(ctx.engine, tid, date(2027, 7, 2), date(2027, 7, 10))
    check(ctx.engine, a, date(2027, 2, 28), datetime(2027, 2, 28, 12, tzinfo=UTC))
    check(ctx.engine, b, date(2027, 2, 20), datetime(2027, 2, 20, 12, tzinfo=UTC))
    check(ctx.engine, a, RUN, datetime(2027, 3, 1, 6, tzinfo=UTC), ok=False)  # failed today: still not fresh
    shortlist.run(ctx)
    assert [i for i, _ in ids_in_order(ctx.engine)] == [b, a]


def test_serpapi_only_round_trips_are_audited_before_second_checks(make_ctx):
    serp = FakeLiveSource("serpapi", answering(option(900), source="serpapi"), supports_open_jaw=True)
    ctx, tid = bare(make_ctx, live_sources=[serp])
    waiting = make_rq(ctx.engine, tid, date(2027, 7, 1), date(2027, 7, 9))
    serp_only = make_rq(ctx.engine, tid, date(2027, 7, 2), date(2027, 7, 10))
    hot = make_rq(ctx.engine, tid, RUN + timedelta(days=5), RUN + timedelta(days=13))
    # open-jaw priced by SerpApi today is never an audit (Google can't price it); hot, so a second check
    jaw = make_rq(
        ctx.engine, tid, RUN + timedelta(days=6), RUN + timedelta(days=14), dest="OPO", return_airport="SCQ"
    )
    fresh_today(ctx.engine, serp_only, "serpapi")
    fresh_today(ctx.engine, hot)
    fresh_today(ctx.engine, jaw, "serpapi")
    shortlist.run(ctx)
    assert ids_in_order(ctx.engine) == [
        (waiting, "explore"),
        (serp_only, "audit"),
        (hot, "second"),
        (jaw, "second"),
    ]


def test_second_checks_are_hot_and_capped(make_ctx):
    ctx, tid = bare(make_ctx)
    confident_baseline(ctx.engine)  # June, week bucket: median 1000, sigma 100
    seen = date(2027, 2, 25)
    near, soon, volatile, cold = [], [], [], []
    for i in range(10):  # near a deal: last live price well under the baseline; cheapest first
        dep = date(2027, 6, 1 + i)
        ret = dep + timedelta(days=8)
        near.append(make_rq(ctx.engine, tid, dep, ret))
        add_observation(ctx.engine, dep, ret, 800 + 10 * i, observed=seen, verified=True)
    for i in range(20):  # departing within SOON_DAYS
        dep = RUN + timedelta(days=2 + i)
        soon.append(make_rq(ctx.engine, tid, dep, dep + timedelta(days=8)))
    for i in range(20):  # prices swinging more with i; no July baseline, so never near-deal
        dep = date(2027, 7, 1 + i)
        ret = dep + timedelta(days=8)
        volatile.append(make_rq(ctx.engine, tid, dep, ret))
        for price in (100, 100 + 10 * (i + 4)):
            add_observation(ctx.engine, dep, ret, price, observed=seen, verified=True)
    for i in range(10):  # nothing going on
        dep = date(2027, 8, 1 + i)
        cold.append(make_rq(ctx.engine, tid, dep, dep + timedelta(days=8)))
    for rq_id in near + soon + volatile + cold:
        fresh_today(ctx.engine, rq_id)
    counts = shortlist.run(ctx)
    got = ids_in_order(ctx.engine)
    assert counts["second"] == 40 and all(reason == "second" for _, reason in got)
    assert [i for i, _ in got] == near + soon + volatile[::-1][:10]
    assert not {i for i, _ in got} & set(cold)
