"""Fakes and seed data for pipeline tests. Run date is 2027-03-01; the seeded user travels in June 2027."""

import random
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import select

from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import LiveCheck, PriceObservation, RouteQuery, Tracker, TravelWindow, User
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.sources.base import ExactQuery, ExactResult, FareQuote, FlightOption, SourceUnavailable

RUN = date(2027, 3, 1)
GEO = load_geo()
SEASONS = load_seasons()


class FakeMonthSource:
    name = "fake_month"

    def __init__(self, quotes: dict | None = None):
        self.quotes = quotes or {}  # (origin, dest, month) -> list[FareQuote] | Exception
        self.calls: list[tuple] = []

    def month_scan(self, origin, dest_airport, month, market, currency):
        self.calls.append((origin, dest_airport, month, market, currency))
        found = self.quotes.get((origin, dest_airport, month), [])
        if isinstance(found, Exception):
            raise found
        return found


class FakeLiveSource:
    def __init__(
        self, name: str, respond: Callable[[ExactQuery], ExactResult], supports_open_jaw: bool = False
    ):
        self.name = name
        self.respond = respond
        self.supports_open_jaw = supports_open_jaw
        self.calls: list[ExactQuery] = []

    def exact_search(self, query):
        self.calls.append(query)
        return self.respond(query)


def option(price, stops=1, duration=780, dep=time(18, 0), overnight=False, day=None) -> FlightOption:
    return FlightOption(
        price=float(price),
        carrier="TAP",
        stops=stops,
        duration_min=duration,
        outbound_departure=datetime.combine(day or date(2027, 6, 5), dep),
        flight_numbers=("TP 246",),
        overnight_layover=overnight,
    )


def answering(*options: FlightOption, typical=None, source="google_flights"):
    def respond(q: ExactQuery) -> ExactResult:
        return ExactResult(source, q, "USD", tuple(options), "https://flights.example/x", typical)

    return respond


def failing(message="blocked"):
    def respond(q):
        raise SourceUnavailable(message)

    return respond


def quote(origin, dest, depart, ret, price) -> FareQuote:
    return FareQuote(
        "travelpayouts", origin, dest, depart, ret, float(price), "USD", "TP", "TP 246", 1, 1, 760
    )


def add_user(
    engine, email="nick@example.com", windows=((date(2027, 6, 1), date(2027, 6, 30)),), **fields
) -> int:
    values = {
        "email": email,
        "home_airport": "ORD",
        "country": "US",
        "holiday_calendar": "US",
        "pto_days_total": 15,
        "max_trip_days": 16,
    } | fields
    with session_scope(engine) as s:
        user = User(**values)
        s.add(user)
        s.flush()
        for start, end in windows:
            s.add(TravelWindow(user_id=user.id, start_date=start, end_date=end))
        return user.id


def add_tracker(engine, user_id, code="LIS", min_stay=5, max_stay=9, **fields) -> int:
    with session_scope(engine) as s:
        t = Tracker(
            user_id=user_id, destination_code=code, min_stay_days=min_stay, max_stay_days=max_stay, **fields
        )
        s.add(t)
        s.flush()
        return t.id


def add_observation(
    engine,
    depart,
    ret,
    price,
    observed: date,
    verified=False,
    origin="ORD",
    dest="LIS",
    return_airport=None,
    **fields,
):
    with session_scope(engine) as s:
        s.add(
            PriceObservation(
                origin=origin,
                dest_airport=dest,
                return_airport=return_airport or dest,
                depart_date=depart,
                return_date=ret,
                month=depart.replace(day=1),
                source="google_flights" if verified else "travelpayouts",
                price=Decimal(str(price)),
                currency="USD",
                verified=verified,
                observed_at=datetime.combine(observed, time(12), UTC),
                **fields,
            )
        )


def add_live_check(
    engine, depart, ret, run_date: date, ok=True, origin="ORD", dest="LIS", source="google_flights"
):
    """Record that a route was live-checked on run_date (the route query must already exist)."""
    with session_scope(engine) as s:
        rq_id = s.scalar(
            select(RouteQuery.id).filter_by(
                origin=origin, dest_airport=dest, depart_date=depart, return_date=ret
            )
        )
        s.add(LiveCheck(run_date=run_date, route_query_id=rq_id, source=source, ok=ok))


@pytest.fixture
def make_ctx(clean_engine):
    def make(**overrides) -> RunContext:
        fields = {
            "run_date": RUN,
            "engine": clean_engine,
            "geo": GEO,
            "seasons": SEASONS,
            "sleep": lambda seconds: None,
            "rng": random.Random(0),
        } | overrides
        return RunContext(**fields)

    return make
