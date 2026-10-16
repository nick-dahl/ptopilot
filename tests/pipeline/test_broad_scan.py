from datetime import date

import pytest
from sqlalchemy import select

from ptopilot.db.models import PriceObservation
from ptopilot.db.session import session_scope
from ptopilot.pipeline import broad_scan, expand
from ptopilot.pipeline.context import StageFailed, StageSkipped
from ptopilot.sources.base import SourceUnavailable
from tests.pipeline.conftest import RUN, FakeMonthSource, add_tracker, add_user, quote

JUNE = date(2027, 6, 1)


def observations(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(PriceObservation).order_by(PriceObservation.id)))


def test_skipped_without_a_month_source(make_ctx):
    with pytest.raises(StageSkipped, match="TRAVELPAYOUTS_TOKEN"):
        broad_scan.run(make_ctx())


def test_one_scan_per_route_month_and_unverified_rows(make_ctx):
    source = FakeMonthSource(
        {
            ("ORD", "LIS", JUNE): [
                quote("ORD", "LIS", date(2027, 6, 12), date(2027, 6, 20), 640),
                quote("ORD", "LIS", date(2027, 6, 14), None, 300),  # one-way: ignored
            ]
        }
    )
    ctx = make_ctx(month_source=source)
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    counts = broad_scan.run(ctx)
    assert source.calls == [("ORD", "LIS", JUNE, "US", "USD")]
    assert counts == {"scans_ok": 1, "quotes": 1}
    [obs] = observations(ctx.engine)
    assert (obs.depart_date, obs.return_date, obs.price, obs.verified) == (
        date(2027, 6, 12),
        date(2027, 6, 20),
        640,
        False,
    )
    assert obs.month == JUNE
    assert obs.observed_at.date() == RUN  # stamped on the run date, not the wall clock


def test_partial_failure_is_counted_not_fatal(make_ctx):
    source = FakeMonthSource(
        {
            ("ORD", "LIS", JUNE): SourceUnavailable("HTTP 500"),
            ("MDW", "LIS", JUNE): [quote("MDW", "LIS", date(2027, 6, 12), date(2027, 6, 20), 700)],
        }
    )
    ctx = make_ctx(month_source=source)
    add_tracker(ctx.engine, add_user(ctx.engine, nearby_airports=["MDW"]))
    expand.run(ctx)
    assert broad_scan.run(ctx) == {"scans_failed": 1, "scans_ok": 1, "quotes": 1}


def test_all_scans_failing_fails_the_stage(make_ctx):
    source = FakeMonthSource({("ORD", "LIS", JUNE): SourceUnavailable("HTTP 401: Unauthorized")})
    ctx = make_ctx(month_source=source)
    add_tracker(ctx.engine, add_user(ctx.engine))
    expand.run(ctx)
    with pytest.raises(StageFailed, match="401"):
        broad_scan.run(ctx)
