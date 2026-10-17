from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from ptopilot.db.models import PriceObservation, RouteQuery, ShortlistEntry


def route(session):
    rq = RouteQuery(
        origin="ORD",
        dest_airport="LIS",
        return_airport="LIS",
        depart_date=date(2027, 6, 12),
        return_date=date(2027, 6, 20),
    )
    session.add(rq)
    session.flush()
    return rq


def test_shortlist_entry_round_trip_and_uniqueness(session):
    rq = route(session)
    session.add(
        ShortlistEntry(run_date=date(2027, 3, 1), route_query_id=rq.id, rank=1, reason="deal", est_price=800)
    )
    session.flush()
    session.add(ShortlistEntry(run_date=date(2027, 3, 1), route_query_id=rq.id, rank=2, reason="explore"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_shortlist_reason_is_checked(session):
    rq = route(session)
    session.add(ShortlistEntry(run_date=date(2027, 3, 1), route_query_id=rq.id, rank=1, reason="hunch"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_observation_stores_google_typical_range(session):
    obs = PriceObservation(
        origin="ORD",
        dest_airport="LIS",
        return_airport="LIS",
        month=date(2027, 6, 1),
        source="serpapi",
        price=Decimal("905.00"),
        currency="USD",
        typical_low=Decimal("780.00"),
        typical_high=Decimal("1150.00"),
    )
    session.add(obs)
    session.flush()
    session.expire_all()
    loaded = session.get(PriceObservation, obs.id)
    assert (loaded.typical_low, loaded.typical_high) == (Decimal("780.00"), Decimal("1150.00"))
