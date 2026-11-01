"""The prune stage applies the retention rule to price_observations (run date 2026-11-01)."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from ptopilot.db.models import Candidate, PriceObservation, RouteQuery, Tracker
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, prune
from ptopilot.pipeline.runner import CONTINUE_ON_FAILURE, STAGES
from tests.pipeline.conftest import add_observation, add_tracker, add_user

TODAY = date(2026, 11, 1)


def _ids(engine) -> set[date]:
    with session_scope(engine) as s:
        return {o.depart_date or o.month for o in s.scalars(select(PriceObservation))}


def _month_only(engine, month, observed=TODAY):
    with session_scope(engine) as s:
        s.add(
            PriceObservation(
                origin="ORD",
                dest_airport="LIS",
                return_airport="LIS",
                depart_date=None,
                return_date=None,
                month=month,
                source="travelpayouts",
                price=Decimal("500"),
                currency="USD",
                observed_at=datetime.combine(observed, time(12), UTC),
            )
        )


def test_departed_more_than_90_days_ago_is_deleted(make_ctx, clean_engine):
    for depart in (date(2026, 8, 2), date(2026, 8, 3), date(2027, 3, 1)):
        add_observation(clean_engine, depart, depart + timedelta(days=7), 500, TODAY)
    ctx = make_ctx(run_date=TODAY)
    assert prune.run(ctx) == {"deleted": 1}
    assert _ids(clean_engine) == {date(2026, 8, 3), date(2027, 3, 1)}


def test_anything_observed_over_13_months_ago_is_deleted(make_ctx, clean_engine):
    depart = date(2027, 3, 1)
    add_observation(clean_engine, depart, depart + timedelta(days=7), 500, TODAY - timedelta(days=396))
    add_observation(clean_engine, depart, depart + timedelta(days=8), 500, TODAY - timedelta(days=395))
    ctx = make_ctx(run_date=TODAY)
    assert prune.run(ctx) == {"deleted": 1}
    with session_scope(clean_engine) as s:
        assert [o.return_date for o in s.scalars(select(PriceObservation))] == [date(2027, 3, 9)]


def test_month_only_rows_are_kept_until_their_month_is_long_past(make_ctx, clean_engine):
    for month in (date(2026, 7, 1), date(2026, 8, 1), date(2027, 1, 1)):
        _month_only(clean_engine, month)
    ctx = make_ctx(run_date=TODAY)
    assert prune.run(ctx) == {"deleted": 1}
    assert _ids(clean_engine) == {date(2026, 8, 1), date(2027, 1, 1)}


def test_dry_run_counts_without_deleting(make_ctx, clean_engine):
    add_observation(clean_engine, date(2026, 8, 2), date(2026, 8, 9), 500, TODAY)
    ctx = make_ctx(run_date=TODAY, dry_run=True)
    assert prune.run(ctx) == {"would_delete": 1}
    assert len(_ids(clean_engine)) == 1


def test_pruning_keeps_candidates(make_ctx, clean_engine):
    ctx = make_ctx(run_date=TODAY)
    tracker_id = add_tracker(clean_engine, add_user(clean_engine))
    expand.run(ctx)
    add_observation(clean_engine, date(2026, 8, 2), date(2026, 8, 9), 500, TODAY)
    with session_scope(clean_engine) as s:
        tracker = s.get(Tracker, tracker_id)
        rq = s.scalars(select(RouteQuery).limit(1)).one()
        obs = s.scalars(select(PriceObservation)).one()
        cand = Candidate(
            user_id=tracker.user_id, tracker_id=tracker_id, route_query_id=rq.id, run_date=TODAY,
            price_observation_id=obs.id, price=Decimal(500), currency="USD", deal_level="none",
            go_now=0, confidence="low", verified=False,
        )  # fmt: skip
        s.add(cand)
        s.flush()
        cand_id = cand.id
    assert prune.run(ctx) == {"deleted": 1}
    with session_scope(clean_engine) as s:
        assert s.get(Candidate, cand_id).price_observation_id is None


def test_prune_runs_last_and_never_blocks():
    assert list(STAGES)[-1] == "prune"
    assert "prune" in CONTINUE_ON_FAILURE
