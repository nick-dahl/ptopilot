"""What the year planner page shows: trips with a bottom line, the PTO budget and a 12-month calendar."""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from ptopilot import config
from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.combos import Leg, find_combinations
from ptopilot.core.fit import BookedTrip
from ptopilot.core.geo import Destination, Geo, UnknownCodeError, palette
from ptopilot.core.planner import target_band
from ptopilot.core.seasons import SeasonTable
from ptopilot.core.yearplan import allocate_pto, month_grid
from ptopilot.db.models import PlanningYear, User
from ptopilot.db.session import session_scope
from ptopilot.digest.select import latest_run_date
from ptopilot.plan_totals import trip_estimates, year_totals
from ptopilot.planning import booked_trips, year_ranges, year_trackers
from ptopilot.web.history import DIMMED_STATES, _options, building_history


def fewest_days_away(geo: Geo, homes: Sequence[str], dest: Destination) -> int:
    """The shortest trip to this place from any of the homes (0 when a route is unknown)."""
    try:
        return min(geo.travel_rule(h, dest).min_trip_days for h in homes)
    except UnknownCodeError:
        return 0


def too_short(geo: Geo, homes: Sequence[str], dest: Destination, target_days: int | None) -> int | None:
    """The fewest days away trips there take, when the target is shorter than that."""
    if target_days is None:
        return None
    needed = fewest_days_away(geo, homes, dest)
    return needed if target_days < needed else None


def _month_weeks(
    year: int,
    month: int,
    cal: WorkCalendar,
    open_ranges: Sequence[tuple[date, date]] = (),
    booked: Sequence[BookedTrip] = (),
) -> list[list[dict | None]]:
    """One month of the tap-calendar: weeks of day cells (None pads the first and last week)."""

    def cell(d: date | None):
        if d is None:
            return None
        trip = next((b for b in booked if b.depart <= d <= b.ret), None)
        return {
            "booked": trip.destination if trip else None,
            "date": d,
            "weekend": d.weekday() >= 5,
            "holiday": cal.holiday_name(d),
            "day_off": d in cal.extra_days_off,
            "open": any(a <= d <= b for a, b in open_ranges),
        }

    return [[cell(d) for d in week] for week in month_grid(year, month)]


def _months(
    year: int,
    cal: WorkCalendar,
    open_ranges: Sequence[tuple[date, date]],
    booked: Sequence[BookedTrip] = (),
):
    return [(calendar.month_name[m], _month_weeks(year, m, cal, open_ranges, booked)) for m in range(1, 13)]


def months_ahead(start: date, cal: WorkCalendar, count: int = 12):
    """`count` months of the tap-calendar from `start`'s month, each named with its year ("March 2027").

    The profile's company days off use it: the planner's calendar, for the coming year."""
    out = []
    year, month = start.year, start.month
    for _ in range(count):
        out.append((f"{calendar.month_name[month]} {year}", _month_weeks(year, month, cal)))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def blank_range_rows(saved: Sequence[tuple[str, str]]) -> list[dict[str, str]]:
    rows = [{"start": a, "end": b} for a, b in saved]
    return rows + [{"start": "", "end": ""} for _ in range(config.EXTRA_RANGE_ROWS)]


def _combinations(
    s,
    geo: Geo,
    seasons: SeasonTable,
    trackers,
    year: int,
    run_date: date | None,
    booked: Sequence[BookedTrip],
    remaining: int,
):
    """Sets of this year's unbooked destinations whose latest offers are all fantastic and fit together."""
    if run_date is None or not trackers:
        return []
    names = {}
    for t in trackers:
        try:
            names[t.id] = geo.destination(t.destination_code).name
        except UnknownCodeError:
            continue
    trackers = [t for t in trackers if t.id in names]
    legs = [
        Leg(
            tracker_id=o.tracker_id,
            destination=names[o.tracker_id],
            candidate_id=o.candidate_id,
            depart=o.depart_date,
            ret=o.return_date,
            pto_cost=o.pto_cost,
            price=o.price,
            typical=Decimal(str(o.median)),
            currency=o.currency,
            confidence=o.confidence,
            season_rating=o.season_rating,
            deep_link=o.deep_link,
        )
        for options in _options(s, geo, seasons, trackers, run_date).values()
        for o in options
        if o.median and o.depart_date.year == year and o.state not in DIMMED_STATES and not o.ruled_out
    ]
    return find_combinations(legs, booked, remaining)


def plan_context(
    engine: Engine, geo: Geo, seasons: SeasonTable, user_id: int, year: int, today: date
) -> dict | None:
    """Everything the page needs, or None when the user has no such planning year."""
    run_date = latest_run_date(engine, today)
    with session_scope(engine) as s:
        user = s.get(User, user_id)
        py = s.get(PlanningYear, (user_id, year)) if user else None
        if py is None:
            return None
        homes = [user.home_airport, *user.nearby_airports]
        saved = year_ranges(s, user, year)
        estimates = trip_estimates(s, user, year, geo, seasons)
        totals = year_totals(s, user, year, geo, seasons, estimates=estimates)
        bookings = {b.tracker_id: b for b in booked_trips(s, user, [year], geo=geo)}
        entries = []
        for t in year_trackers(s, user, year):
            try:
                dest = geo.destination(t.destination_code)
            except UnknownCodeError:
                continue
            needed = fewest_days_away(geo, homes, dest)
            band = (
                target_band(t.target_days, config.TARGET_TOLERANCE_DAYS, needed)
                if t.target_days is not None
                else None
            )
            booking = bookings.get(t.id)
            entries.append(
                {
                    "tracker_id": t.id,
                    "name": dest.name,
                    "palette": palette(dest),
                    "target_days": t.target_days,
                    "band": band,
                    "booking": booking,
                    "days_away": (booking.ret - booking.depart).days + 1 if booking else t.target_days,
                    "est_pto": booking.pto_cost if booking else estimates.get(t.id),
                    "min_trip": too_short(geo, homes, dest, t.target_days),
                    "building_history": building_history(s, homes, dest),
                    "snoozed_until": t.snoozed_until
                    if t.snoozed_until and t.snoozed_until >= today
                    else None,
                }
            )
        # Booked trips are paid for first; the planned ones share what is left, in planner order.
        over = allocate_pto(
            [(e["tracker_id"], e["est_pto"]) for e in entries if not e["booking"]], totals.remaining
        )
        for e in entries:
            e["wont_fit"] = over.get(e["tracker_id"])
        cal = WorkCalendar.from_code(user.holiday_calendar, user.extra_days_off, user.ignored_holidays)
        calendar_bookings = booked_trips(s, user, [year - 1, year], geo=geo)
        watched = [
            t
            for t in year_trackers(s, user, year)
            if t.id not in bookings and not (t.snoozed_until and t.snoozed_until >= today)
        ]
        combos = _combinations(
            s, geo, seasons, watched, year, run_date, calendar_bookings, max(totals.remaining, 0)
        )
        return {
            "year": year,
            "pto_days": py.pto_days,
            "other_time_off": py.other_time_off,
            "available": totals.available,
            "trips": entries,
            "combos": combos,
            "palettes": {e["tracker_id"]: e["palette"] for e in entries},
            "pto_remaining": max(totals.remaining, 0),
            "totals": {
                "trips": len(entries),
                "days_away": sum(e["days_away"] or 0 for e in entries),
                "est_pto": totals.booked + totals.planned,
                "booked": totals.booked,
                "left": totals.left,
            },
            "months": _months(year, cal, saved, calendar_bookings),
            "spill": [(a.isoformat(), b.isoformat()) for a, b in saved if b > date(year, 12, 31)],
            "ranges": blank_range_rows([(a.isoformat(), b.isoformat()) for a, b in saved]),
        }
