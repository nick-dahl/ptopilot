"""Seed helpers for digest tests: a candidate plus everything it joins to."""

from datetime import UTC, date, datetime, time
from decimal import Decimal

from ptopilot.db.models import (
    Candidate,
    PriceObservation,
    RouteBaseline,
    RouteQuery,
    Tracker,
    TrackerRouteLink,
    User,
)
from ptopilot.db.session import session_scope

RUN = date(2027, 3, 4)  # a Thursday
MONDAY = date(2027, 3, 1)


def add_user(engine, email="nick@example.com") -> int:
    with session_scope(engine) as s:
        u = User(
            email=email,
            home_airport="JFK",
            country="US",
            holiday_calendar="US",
            pto_days_total=15,
            max_trip_days=16,
        )
        s.add(u)
        s.flush()
        return u.id


def add_tracker(engine, user_id, code="AZORES", **fields) -> int:
    with session_scope(engine) as s:
        t = Tracker(user_id=user_id, destination_code=code, min_stay_days=7, max_stay_days=10, **fields)
        s.add(t)
        s.flush()
        return t.id


def add_candidate(
    engine,
    tracker_id,
    price,
    depart=date(2027, 3, 5),
    ret=date(2027, 3, 14),
    level="good",
    go_now=60,
    run_date=RUN,
    dest="PDL",
    return_airport=None,
    origin="JFK",
    evening=True,
    days_off=(),
    verified=True,
) -> int:
    """A candidate with its route query, link and live observation."""
    with session_scope(engine) as s:
        user_id = s.get(Tracker, tracker_id).user_id
        rq = (
            s.query(RouteQuery)
            .filter_by(
                origin=origin,
                dest_airport=dest,
                return_airport=return_airport or dest,
                depart_date=depart,
                return_date=ret,
            )
            .one_or_none()
        )
        if rq is None:
            rq = RouteQuery(
                origin=origin,
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
                run_date=run_date,
                evening_departure=evening,
                pto_cost=5,
                days_away=(ret - depart).days + 1,
                efficiency=2.0,
                month=depart.month,
                season_rating="shoulder",
                days_off=list(days_off),
            )
        )
        obs = PriceObservation(
            origin=origin,
            dest_airport=dest,
            return_airport=return_airport or dest,
            depart_date=depart,
            return_date=ret,
            month=depart.replace(day=1),
            source="google_flights",
            price=Decimal(str(price)),
            currency="USD",
            carrier="Tap Air Portugal",
            stops=1,
            duration_min=420,
            outbound_departure=datetime.combine(depart, time(22, 0)),
            flight_numbers=["TP 202"],
            deep_link="https://www.google.com/travel/flights/search?tfs=X",
            verified=verified,
            observed_at=datetime.combine(run_date, time(6), UTC),
        )
        s.add(obs)
        s.flush()
        c = Candidate(
            user_id=user_id,
            tracker_id=tracker_id,
            route_query_id=rq.id,
            price_observation_id=obs.id,
            run_date=run_date,
            evening_departure=evening,
            price=Decimal(str(price)),
            currency="USD",
            z=-1.6,
            deal_level=level,
            go_now=go_now,
            confidence="normal",
            verified=verified,
        )
        s.add(c)
        s.flush()
        return c.id


def add_baseline(engine, median, dest="PDL", month=date(2027, 3, 1), bucket="week", return_airport=None):
    with session_scope(engine) as s:
        s.add(
            RouteBaseline(
                origin="JFK",
                dest_airport=dest,
                return_airport=return_airport or dest,
                month=month,
                length_bucket=bucket,
                median=Decimal(median),
                sigma=Decimal(50),
                n=20,
                confidence="normal",
            )
        )


def book(engine, user_id, tracker_id, depart, ret, geo=None, **kw):
    """Plan the tracker in the departure's year (if it is not yet) and book that trip."""
    from sqlalchemy import select

    from ptopilot.data import load_geo
    from ptopilot.db.models import PlannedTrip, User
    from ptopilot.planning import book_trip

    with session_scope(engine) as s:
        have = s.scalar(
            select(PlannedTrip.id).where(
                PlannedTrip.tracker_id == tracker_id, PlannedTrip.year == depart.year
            )
        )
        if have is None:
            s.add(PlannedTrip(user_id=user_id, year=depart.year, tracker_id=tracker_id))
            s.flush()
        book_trip(s, s.get(User, user_id), tracker_id, depart.year, depart, ret, geo=geo or load_geo(), **kw)
