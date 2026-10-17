from datetime import date
from decimal import Decimal

from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import RouteBaseline, RouteQuery, ShortlistEntry
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, shortlist
from tests.pipeline.conftest import RUN, add_live_check, add_observation, add_tracker, add_user

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


def test_exploration_fills_check_slots_that_deals_leave_unused(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "LIVE_CHECK_CAP", 3)
    monkeypatch.setattr(config, "EXPLORATION_QUOTA", 2)
    ctx = setup(make_ctx)
    counts = shortlist.run(ctx)  # no history: 6 exploration candidates, no deals
    assert (counts["explore"], counts["explore_overflow"]) == (3, 3)
    assert len(entries(ctx.engine)) == 3


def test_exploration_keeps_its_reserved_slots_when_deals_overflow(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "LIVE_CHECK_CAP", 3)
    monkeypatch.setattr(config, "EXPLORATION_QUOTA", 1)
    ctx = setup(make_ctx)
    confident_baseline(ctx.engine)  # "week" trips only; the two 11-day trips stay exploration
    add_observation(ctx.engine, *DEAL, 800, observed=RUN)  # June's cheapest: makes week trips look like deals
    counts = shortlist.run(ctx)
    assert (counts["deal"], counts["explore"]) == (2, 1)
    assert [reason for _, reason, _, _ in entries(ctx.engine)] == ["deal", "deal", "explore"]


def test_rerun_replaces_the_days_shortlist(make_ctx):
    ctx = setup(make_ctx)
    shortlist.run(ctx)
    shortlist.run(ctx)
    assert [rank for rank, *_ in entries(ctx.engine)] == [1, 2, 3, 4, 5, 6]


def test_same_day_rerun_keeps_the_same_exploration_picks(make_ctx, monkeypatch):
    monkeypatch.setattr(config, "EXPLORATION_QUOTA", 2)
    ctx = setup(make_ctx)
    shortlist.run(ctx)
    first = [dates for _, _, dates, _ in entries(ctx.engine)]
    for dep, ret in first:  # live_verify checked them earlier today
        add_live_check(ctx.engine, dep, ret, run_date=RUN)
    shortlist.run(ctx)
    assert [dates for _, _, dates, _ in entries(ctx.engine)] == first
