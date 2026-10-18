"""Deferred polish from Plan 8's review: history rows stay out of the broad scan, the audit pairs like with
like, duplicate history isn't re-stored, and the counts and labels say what happened."""

import tomllib
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import func, select

from ptopilot import config
from ptopilot.db.models import PriceObservation, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import broad_scan, expand
from ptopilot.pipeline.health import audit_lines
from ptopilot.pipeline.live_verify import store_history
from ptopilot.sources.base import ExactQuery, ExactResult
from tests.pipeline.conftest import RUN, FakeMonthSource, add_tracker, add_user

ROOT = Path(__file__).resolve().parents[2]


def observe(engine, origin, dest, ret, depart, back, source, price, verified, day=RUN):
    with session_scope(engine) as s:
        s.add(
            PriceObservation(
                origin=origin, dest_airport=dest, return_airport=ret, depart_date=depart, return_date=back,
                month=depart.replace(day=1), source=source, price=Decimal(price), currency="USD",
                verified=verified, observed_at=datetime.combine(day, time(12), UTC),
            )
        )  # fmt: skip


def test_todays_history_point_does_not_count_as_a_broad_scan(make_ctx):
    month_source = FakeMonthSource()
    ctx = make_ctx(month_source=month_source)
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    observe(
        ctx.engine, "ORD", "LIS", "LIS", date(2027, 6, 12), date(2027, 6, 20), "google_history", 900, False
    )
    broad_scan.run(ctx)
    assert ("ORD", "LIS", date(2027, 6, 1)) in {(o, d, m) for o, d, m, *_ in month_source.calls}


def test_the_audit_never_pairs_an_open_jaw_fare_with_a_round_trip(clean_engine):
    trip = (date(2027, 3, 5), date(2027, 3, 19))
    observe(clean_engine, "JFK", "OPO", "OPO", *trip, "google_flights", 700, True)
    observe(clean_engine, "JFK", "OPO", "SCQ", *trip, "serpapi", 852, True)
    with session_scope(clean_engine) as s:
        assert (
            audit_lines(s, RUN)[0]
            == "Audit (fast-flights vs SerpApi, today): no trips priced by both sources"
        )


def test_when_fast_flights_was_never_pricier_the_audit_says_so(clean_engine):
    trip = (date(2027, 3, 5), date(2027, 3, 14))
    observe(clean_engine, "JFK", "PDL", "PDL", *trip, "google_flights", 600, True)
    observe(clean_engine, "JFK", "PDL", "PDL", *trip, "serpapi", 650, True)
    with session_scope(clean_engine) as s:
        lines = audit_lines(s, RUN)
    assert lines[1] == "  median gap -$50 (-8%); fast-flights was never pricier"


def test_history_already_stored_for_a_trip_and_day_is_not_stored_again(make_ctx):
    ctx = make_ctx()
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    with session_scope(ctx.engine) as s:
        rq = s.scalars(select(RouteQuery).order_by(RouteQuery.id)).first()
        s.expunge(rq)
    points = tuple((RUN - timedelta(days=i), 1000.0) for i in range(5))
    query = ExactQuery(rq.origin, rq.dest_airport, rq.depart_date, rq.return_date)
    result = ExactResult("serpapi", query, "USD", (), "", None, points)
    assert store_history(ctx, rq, result) == 5
    more = ExactResult("serpapi", query, "USD", (), "", None, ((RUN - timedelta(days=5), 990.0), *points))
    assert store_history(ctx, rq, more) == 1  # only the new day
    with session_scope(ctx.engine) as s:
        stored = s.scalar(select(func.count()).where(PriceObservation.source == config.HISTORY_SOURCE))
    assert stored == 6


def test_seed_history_can_be_run_alone_from_the_actions_page():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "scan.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))  # PyYAML reads the bare key `on` as True
    options = triggers["workflow_dispatch"]["inputs"]["stage"]["options"]
    assert "seed_history" in options and options.index("seed_history") == options.index("shortlist") + 1


def test_fast_flights_is_pinned_and_selectolax_declared():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert "fast-flights~=3.1.0" in deps
    assert any(d.startswith("selectolax") for d in deps)
