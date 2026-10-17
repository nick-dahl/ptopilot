from datetime import date, time
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ptopilot.db.models import (
    DigestSend,
    PriceObservation,
    RouteQuery,
    Tracker,
    TravelWindow,
    User,
)


def make_user(session, **overrides):
    fields = {
        "email": "nick@example.com",
        "home_airport": "ORD",
        "country": "US",
        "holiday_calendar": "US",
        "pto_days_total": 20,
        "max_trip_days": 16,
    } | overrides
    user = User(**fields)
    session.add(user)
    session.flush()
    return user


def test_user_defaults_and_arrays_round_trip(session):
    user = make_user(session, nearby_airports=["MDW"], extra_days_off=[date(2027, 11, 26)])
    session.expire_all()
    loaded = session.get(User, user.id)
    assert loaded.nearby_airports == ["MDW"]
    assert loaded.extra_days_off == [date(2027, 11, 26)]
    assert loaded.ignored_holidays == []
    assert (loaded.currency, loaded.weather_tolerance, loaded.min_trip_days) == ("USD", "normal", 3)
    assert loaded.friday_evening_min_time == time(17, 0)
    assert loaded.created_at is not None


def test_user_email_is_unique(session):
    make_user(session)
    with pytest.raises(IntegrityError):
        make_user(session)


@pytest.mark.parametrize(
    "overrides",
    [
        {"weather_tolerance": "sunny"},
        {"min_trip_days": 10, "max_trip_days": 5},
        {"pto_days_total": -1},
    ],
)
def test_user_checks_reject_bad_values(session, overrides):
    with pytest.raises(IntegrityError):
        make_user(session, **overrides)


def test_deleting_user_cascades_to_trackers_and_windows(session):
    user = make_user(session)
    session.add_all(
        [
            Tracker(user_id=user.id, destination_code="TH", min_stay_days=7, max_stay_days=12),
            TravelWindow(user_id=user.id, start_date=date(2027, 6, 1), end_date=date(2027, 6, 30)),
        ]
    )
    session.flush()
    session.delete(user)
    session.flush()
    assert session.scalar(select(func.count()).select_from(Tracker)) == 0
    assert session.scalar(select(func.count()).select_from(TravelWindow)) == 0


@pytest.mark.parametrize(
    "row",
    [
        lambda uid: Tracker(user_id=uid, destination_code="TH", min_stay_days=12, max_stay_days=7),
        lambda uid: Tracker(
            user_id=uid, destination_code="TH", min_stay_days=7, max_stay_days=12, priority=4
        ),
        lambda uid: TravelWindow(user_id=uid, start_date=date(2027, 6, 30), end_date=date(2027, 6, 1)),
    ],
)
def test_tracker_and_window_checks(session, row):
    user = make_user(session)
    session.add(row(user.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_route_queries_are_unique(session):
    def rq():
        return RouteQuery(
            origin="ORD",
            dest_airport="LIS",
            return_airport="LIS",
            depart_date=date(2027, 6, 11),
            return_date=date(2027, 6, 20),
        )

    session.add(rq())
    session.flush()
    session.add(rq())
    with pytest.raises(IntegrityError):
        session.flush()


def test_price_observation_round_trip(session):
    obs = PriceObservation(
        origin="ORD",
        dest_airport="LIS",
        return_airport="LIS",
        depart_date=date(2027, 6, 11),
        return_date=date(2027, 6, 20),
        month=date(2027, 6, 1),
        source="serpapi",
        price=Decimal("905.00"),
        currency="USD",
        flight_numbers=["UA 1234", "TP 202"],
        verified=True,
    )
    session.add(obs)
    session.flush()
    session.expire_all()
    loaded = session.get(PriceObservation, obs.id)
    assert loaded.price == Decimal("905.00")
    assert loaded.flight_numbers == ["UA 1234", "TP 202"]
    assert loaded.observed_at is not None


def test_digest_items_json_round_trip(session):
    user = make_user(session)
    send = DigestSend(user_id=user.id, items=[{"candidate_id": 1, "price": 612.0}])
    session.add(send)
    session.flush()
    session.expire_all()
    assert session.get(DigestSend, send.id).items == [{"candidate_id": 1, "price": 612.0}]
