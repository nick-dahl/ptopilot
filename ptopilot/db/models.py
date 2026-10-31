"""SQLAlchemy models for every table in spec §5."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Money = Numeric(10, 2)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("weather_tolerance IN ('strict', 'normal', 'relaxed')", name="weather_tolerance"),
        CheckConstraint("0 < min_trip_days AND min_trip_days <= max_trip_days", name="trip_days"),
        CheckConstraint("pto_days_total >= 0 AND pto_committed >= 0", name="pto_nonneg"),
        CheckConstraint(
            "ideal_trip_days IS NULL"
            " OR (min_trip_days <= ideal_trip_days AND ideal_trip_days <= max_trip_days)",
            name="ideal_trip_days",
        ),
        CheckConstraint("welcome_step BETWEEN 0 AND 4", name="welcome_step"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    home_airport: Mapped[str] = mapped_column(String(3))
    nearby_airports: Mapped[list[str]] = mapped_column(ARRAY(String(3)), server_default="{}")
    country: Mapped[str] = mapped_column(String(2))
    currency: Mapped[str] = mapped_column(String(3), server_default="USD")
    holiday_calendar: Mapped[str] = mapped_column(String(16))
    extra_days_off: Mapped[list[date]] = mapped_column(ARRAY(Date), server_default="{}")
    ignored_holidays: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    pto_days_total: Mapped[int] = mapped_column(SmallInteger)
    pto_committed: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    min_trip_days: Mapped[int] = mapped_column(SmallInteger, server_default="3")
    max_trip_days: Mapped[int] = mapped_column(SmallInteger)
    ideal_trip_days: Mapped[int | None] = mapped_column(SmallInteger)  # None: no preferred length
    weather_tolerance: Mapped[str] = mapped_column(String(8), server_default="normal")
    max_stops_short: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    max_stops_long: Mapped[int] = mapped_column(SmallInteger, server_default="2")
    allow_overnight_layover: Mapped[bool] = mapped_column(server_default="false")
    friday_evening_departure: Mapped[bool] = mapped_column(server_default="false")
    friday_evening_min_time: Mapped[time] = mapped_column(Time, server_default="17:00")
    # The guided /welcome flow (web/onboarding.py). A user made any other way (the YAML loader, a full
    # profile form, plain SQL) is onboarded on creation; the flow's step 1 inserts NULL explicitly.
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    welcome_step: Mapped[int] = mapped_column(SmallInteger, server_default="0")  # furthest step finished
    created_at: Mapped[datetime] = created_at()


class Invite(Base):
    __tablename__ = "invites"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    invited_at: Mapped[datetime] = created_at()


class TravelWindow(Base):
    __tablename__ = "travel_windows"
    __table_args__ = (CheckConstraint("start_date <= end_date", name="ordered"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date]
    end_date: Mapped[date]


class Tracker(Base):
    __tablename__ = "trackers"
    __table_args__ = (
        CheckConstraint("0 < min_stay_days AND min_stay_days <= max_stay_days", name="stay_days"),
        CheckConstraint("priority BETWEEN 1 AND 3", name="priority"),
        CheckConstraint("target_days IS NULL OR target_days BETWEEN 2 AND 60", name="target_days"),
        UniqueConstraint("user_id", "destination_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    destination_code: Mapped[str] = mapped_column(String(32))
    min_stay_days: Mapped[int] = mapped_column(SmallInteger)
    max_stay_days: Mapped[int] = mapped_column(SmallInteger)
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="2")
    max_price: Mapped[Decimal | None] = mapped_column(Money)
    snoozed_until: Mapped[date | None]
    target_days: Mapped[int | None] = mapped_column(SmallInteger)  # days away; None: use the stay range
    active: Mapped[bool] = mapped_column(server_default="true")
    created_at: Mapped[datetime] = created_at()


class PlanningYear(Base):
    """A year a user is planning: its PTO budget and the days off already spoken for."""

    __tablename__ = "planning_years"
    __table_args__ = (
        CheckConstraint(
            "pto_days >= 0 AND other_time_off >= 0 AND other_time_off <= pto_days", name="pto_days"
        ),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    pto_days: Mapped[int] = mapped_column(SmallInteger)
    other_time_off: Mapped[int] = mapped_column(SmallInteger, server_default="0")  # PTO already committed
    created_at: Mapped[datetime] = created_at()


class PlannedTrip(Base):
    """A tracker's destination picked for a planning year."""

    __tablename__ = "planned_trips"
    __table_args__ = (
        UniqueConstraint("tracker_id", "year"),
        CheckConstraint(
            "(booked_depart IS NULL) = (booked_return IS NULL)"
            " AND (booked_depart IS NULL) = (booked_pto IS NULL)",
            name="booked_dates",
        ),
        CheckConstraint("booked_return >= booked_depart", name="booked_order"),
        CheckConstraint(
            "booked_depart IS NULL OR extract(year from booked_depart) = year", name="booked_year"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    year: Mapped[int] = mapped_column(SmallInteger)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = created_at()
    booked_depart: Mapped[date | None]
    booked_return: Mapped[date | None]
    booked_price: Mapped[Decimal | None] = mapped_column(Money)
    booked_currency: Mapped[str | None] = mapped_column(String(3))
    booked_pto: Mapped[int | None] = mapped_column(SmallInteger)
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def booked(self) -> bool:
        return self.booked_depart is not None


class Destination(Base):
    """A place a user added from the airport catalog; built-in places live in geo.yaml instead."""

    __tablename__ = "destinations"
    __table_args__ = (CheckConstraint("kind IN ('city', 'region', 'route')", name="kind"),)

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(8))
    airports: Mapped[list[str]] = mapped_column(ARRAY(Text))
    return_airports: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    color: Mapped[str | None] = mapped_column(String(7))
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()


class DestinationSeason(Base):
    """Season ratings generated from climate data for an added place."""

    __tablename__ = "destination_seasons"

    code: Mapped[str] = mapped_column(ForeignKey("destinations.code", ondelete="CASCADE"), primary_key=True)
    months: Mapped[list[str]] = mapped_column(ARRAY(Text))  # 12 ratings, January first
    notes: Mapped[dict] = mapped_column(JSONB, server_default="{}")  # {"1": "~8°C, 6 wet days"}
    source: Mapped[str] = mapped_column(String(32))
    computed_at: Mapped[datetime] = created_at()


class TrackerExclusion(Base):
    __tablename__ = "tracker_exclusions"
    __table_args__ = (UniqueConstraint("tracker_id", "depart_date", "return_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    depart_date: Mapped[date]
    return_date: Mapped[date]


class RouteQuery(Base):
    """A shared, de-duplicated search unit (origin, airport, dates) used by any number of trackers."""

    __tablename__ = "route_queries"
    __table_args__ = (
        UniqueConstraint(
            "origin",
            "dest_airport",
            "return_airport",
            "depart_date",
            "return_date",
            name="uq_route_queries_trip",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(3))
    dest_airport: Mapped[str] = mapped_column(String(3))  # fly into
    return_airport: Mapped[str] = mapped_column(String(3))  # fly home from (differs only for open-jaw)
    depart_date: Mapped[date]
    return_date: Mapped[date]


class TrackerRouteLink(Base):
    """Why a tracker wants a route_query on a given run: the trip shape's PTO facts and season."""

    __tablename__ = "tracker_route_links"
    __table_args__ = (UniqueConstraint("tracker_id", "route_query_id", "run_date", "evening_departure"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    route_query_id: Mapped[int] = mapped_column(
        ForeignKey("route_queries.id", ondelete="CASCADE"), index=True
    )
    run_date: Mapped[date] = mapped_column(index=True)
    evening_departure: Mapped[bool] = mapped_column(server_default="false")
    pto_cost: Mapped[int] = mapped_column(SmallInteger)
    days_away: Mapped[int] = mapped_column(SmallInteger)
    efficiency: Mapped[float]
    month: Mapped[int] = mapped_column(SmallInteger)
    season_rating: Mapped[str] = mapped_column(String(8))
    days_off: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")


class PriceObservation(Base):
    """Every price ever seen. Append-only: never update or delete rows."""

    __tablename__ = "price_observations"
    __table_args__ = (
        Index("ix_price_observations_route_month", "origin", "dest_airport", "month"),
        Index("ix_price_observations_route_dates", "origin", "dest_airport", "depart_date", "return_date"),
        Index("ix_price_observations_verified_observed_at", "verified", "observed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    origin: Mapped[str] = mapped_column(String(3))
    dest_airport: Mapped[str] = mapped_column(String(3))
    return_airport: Mapped[str] = mapped_column(String(3))
    depart_date: Mapped[date | None]
    return_date: Mapped[date | None]
    month: Mapped[date]  # first day of the departure month
    source: Mapped[str] = mapped_column(String(32))
    price: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    carrier: Mapped[str | None] = mapped_column(String(120))
    stops: Mapped[int | None] = mapped_column(SmallInteger)
    duration_min: Mapped[int | None] = mapped_column(Integer)
    outbound_departure: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    flight_numbers: Mapped[list[str]] = mapped_column(ARRAY(String(16)), server_default="{}")
    overnight_layover: Mapped[bool | None]
    longest_layover_min: Mapped[int | None] = mapped_column(SmallInteger)
    longest_layover_airport: Mapped[str | None] = mapped_column(String(3))
    deep_link: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(server_default="false")
    typical_low: Mapped[Decimal | None] = mapped_column(
        Money
    )  # Google's typical range, when the source has it
    typical_high: Mapped[Decimal | None] = mapped_column(Money)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShortlistEntry(Base):
    """Route queries picked for a live check on a run, in check order."""

    __tablename__ = "shortlist_entries"
    __table_args__ = (
        UniqueConstraint("run_date", "route_query_id"),
        CheckConstraint("reason IN ('deal', 'explore')", name="reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(index=True)
    route_query_id: Mapped[int] = mapped_column(ForeignKey("route_queries.id", ondelete="CASCADE"))
    rank: Mapped[int] = mapped_column(SmallInteger)
    reason: Mapped[str] = mapped_column(String(8))
    est_price: Mapped[Decimal | None] = mapped_column(Money)


class LiveCheck(Base):
    """One attempted live check, whatever the outcome. Drives same-day re-run skips and daily budgets."""

    __tablename__ = "live_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(index=True)
    route_query_id: Mapped[int] = mapped_column(ForeignKey("route_queries.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))
    ok: Mapped[bool]
    options: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = created_at()
    purpose: Mapped[str] = mapped_column(String(8), server_default="trip")  # 'trip' / 'return' / 'dryret'


class RouteBaseline(Base):
    __tablename__ = "route_baselines"
    __table_args__ = (CheckConstraint("length_bucket IN ('short', 'week', 'long')", name="length_bucket"),)

    origin: Mapped[str] = mapped_column(String(3), primary_key=True)
    dest_airport: Mapped[str] = mapped_column(String(3), primary_key=True)
    return_airport: Mapped[str] = mapped_column(String(3), primary_key=True)
    month: Mapped[date] = mapped_column(primary_key=True)
    length_bucket: Mapped[str] = mapped_column(String(5), primary_key=True)
    median: Mapped[Decimal] = mapped_column(Money)
    sigma: Mapped[Decimal] = mapped_column(Money)
    n: Mapped[int]
    confidence: Mapped[str] = mapped_column(String(6))
    google_typical_low: Mapped[Decimal | None] = mapped_column(Money)
    google_typical_high: Mapped[Decimal | None] = mapped_column(Money)
    computed_at: Mapped[datetime] = created_at()


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("tracker_id", "route_query_id", "run_date", "evening_departure"),
        CheckConstraint("deal_level IN ('none', 'good', 'great')", name="deal_level"),
        CheckConstraint("state IN ('new', 'sent', 'snoozed', 'excluded')", name="state"),
        CheckConstraint("verdict IN ('ok', 'forgiven', 'ruled_out')", name="verdict"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    route_query_id: Mapped[int] = mapped_column(ForeignKey("route_queries.id", ondelete="CASCADE"))
    price_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_observations.id", ondelete="SET NULL")
    )
    run_date: Mapped[date] = mapped_column(index=True)
    evening_departure: Mapped[bool] = mapped_column(server_default="false")
    price: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    z: Mapped[float | None]
    deal_level: Mapped[str] = mapped_column(String(5))
    go_now: Mapped[int] = mapped_column(SmallInteger)
    confidence: Mapped[str] = mapped_column(String(6))
    verified: Mapped[bool]
    state: Mapped[str] = mapped_column(String(8), server_default="new")
    verdict: Mapped[str] = mapped_column(String(9), server_default="ok")
    misery_note: Mapped[str | None] = mapped_column(Text)
    expected_days: Mapped[int | None] = mapped_column(SmallInteger)
    duration_thin: Mapped[bool] = mapped_column(server_default="false")  # a dip, but too little history


class AlertSend(Base):
    """One instant alert sent; at most one per user per UTC day."""

    __tablename__ = "alert_sends"
    __table_args__ = (UniqueConstraint("user_id", "run_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"))
    run_date: Mapped[date]
    sent_at: Mapped[datetime] = created_at()


class DigestSend(Base):
    __tablename__ = "digest_sends"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    sent_at: Mapped[datetime] = created_at()
    items: Mapped[list[dict]] = mapped_column(JSONB, server_default="[]")  # [{"candidate_id", "price"}]


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(index=True)
    stage: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    counts: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)


class SourceBudget(Base):
    __tablename__ = "source_budget"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    period: Mapped[date] = mapped_column(primary_key=True)  # first day of the month
    calls_used: Mapped[int] = mapped_column(server_default="0")


class RelatedLink(Base):
    """A related airport the user accepted (or dismissed) for one of their trackers."""

    __tablename__ = "related_links"
    __table_args__ = (
        CheckConstraint("status IN ('accepted','dismissed')", name="status"),
        UniqueConstraint("tracker_id", "airport"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    airport: Mapped[str] = mapped_column(String(3))
    place_code: Mapped[str] = mapped_column(String(32))  # the destination (built-in or added) it belongs to
    status: Mapped[str] = mapped_column(String(9))
    created_at: Mapped[datetime] = created_at()


class RelatedCheck(Base):
    """One cheap-related-fare check against the main destination's typical price (written by the scan)."""

    __tablename__ = "related_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id", ondelete="CASCADE"))
    link_id: Mapped[int] = mapped_column(ForeignKey("related_links.id", ondelete="CASCADE"))
    origin: Mapped[str] = mapped_column(String(3))
    airport: Mapped[str] = mapped_column(String(3))
    depart_date: Mapped[date]
    return_date: Mapped[date]
    cached_price: Mapped[Decimal] = mapped_column(Money)
    typical_median: Mapped[Decimal] = mapped_column(Money)
    live_price: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    pto_cost: Mapped[int] = mapped_column(SmallInteger)
    deep_link: Mapped[str | None] = mapped_column(Text)
    confirmed: Mapped[bool]
    error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = created_at()


class PlacePhotoRow(Base):
    """A place's cover photo from Wikimedia Commons, found by the scan's `photos` stage.

    `none`: no acceptable photo was found (tried again after a while). Built-in places' photos live in
    geo.yaml instead; ptopilot.photos.photo_for reads both."""

    __tablename__ = "place_photos"
    __table_args__ = (CheckConstraint("status IN ('ok','none')", name="status"),)

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    image_url: Mapped[str | None] = mapped_column(Text)  # a Wikimedia thumbnail, about 1280 px wide
    width: Mapped[int | None]
    height: Mapped[int | None]
    author: Mapped[str | None] = mapped_column(Text)
    licence: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)  # the Commons file page
    status: Mapped[str] = mapped_column(String(4))
    fetched_at: Mapped[datetime] = created_at()
