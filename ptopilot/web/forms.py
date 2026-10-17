"""Profile form <-> the YAML-shaped profile dict, so the web form reuses profiles.parse_profile/apply_profile.

The form flattens lists into numbered fields (window_start_0, tracker_dest_1, ...). Blank rows are
ignored. Values that don't parse as numbers are passed through as text so parse_profile reports them.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from ptopilot.db.models import Tracker, TravelWindow, User

INT_FIELDS = (
    "pto_days_total", "pto_committed", "min_trip_days", "max_trip_days", "max_stops_short", "max_stops_long",
)  # fmt: skip
OPTIONAL_INT_FIELDS = ("ideal_trip_days",)  # blank means "no preference"
TEXT_FIELDS = ("home_airport", "country", "holiday_calendar", "weather_tolerance")
BOOL_FIELDS = ("allow_overnight_layover", "friday_evening_departure")
EXTRA_ROWS = 2  # blank rows offered for new windows and trackers


def _int(value: str):
    value = (value or "").strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return value or None


def _list(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _rows(form: Mapping[str, str], prefix: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    rows, i = [], 0
    while any(f"{prefix}_{f}_{i}" in form for f in fields):
        row = {f: (form.get(f"{prefix}_{f}_{i}") or "").strip() for f in fields}
        if any(row.values()):
            rows.append(row)
        i += 1
    return rows


def form_to_profile(form: Mapping[str, str], email: str) -> dict:
    """Build a profile mapping (the YAML shape) from submitted form fields."""
    data: dict = {"email": email}
    for key in TEXT_FIELDS:
        value = (form.get(key) or "").strip()
        if value:
            data[key] = value.upper() if key in ("home_airport", "country") else value
    for key in INT_FIELDS + OPTIONAL_INT_FIELDS:
        value = _int(form.get(key, ""))
        if value is not None:
            data[key] = value
    for key in BOOL_FIELDS:
        data[key] = form.get(key) in ("on", "true", "1")
    data["nearby_airports"] = [code.upper() for code in _list(form.get("nearby_airports", ""))]
    data["ignored_holidays"] = _list(form.get("ignored_holidays", ""))
    data["extra_days_off"] = _list(form.get("extra_days_off", ""))
    if (form.get("friday_evening_min_time") or "").strip():
        data["friday_evening_min_time"] = form["friday_evening_min_time"].strip()
    data["windows"] = [
        {"start": r["start"], "end": r["end"]} for r in _rows(form, "window", ("start", "end"))
    ]
    trackers = []
    for r in _rows(form, "tracker", ("dest", "min", "max", "priority", "price")):
        if not (r["dest"] or r["min"] or r["max"] or r["price"]):
            continue  # a blank row that only carries the default priority
        t = {"destination": r["dest"], "min_stay": _int(r["min"]), "max_stay": _int(r["max"])}
        if r["priority"]:
            t["priority"] = _int(r["priority"])
        if r["price"]:
            t["max_price"] = r["price"]
        trackers.append(t)
    data["trackers"] = trackers
    return data


def profile_to_form(s: Session, user: User | None) -> dict[str, str]:
    """Current values as form fields (empty defaults for a new traveler)."""
    if user is None:
        form = {
            "weather_tolerance": "normal",
            "holiday_calendar": "US",
            "country": "US",
            "pto_committed": "0",
            "min_trip_days": "3",
            "max_stops_short": "1",
            "max_stops_long": "2",
            "friday_evening_min_time": "17:00",
            "ideal_trip_days": "",
        }
        windows, trackers = [], []
    else:
        form = {key: str(getattr(user, key)) for key in INT_FIELDS} | {
            "ideal_trip_days": str(user.ideal_trip_days) if user.ideal_trip_days is not None else "",
            "home_airport": user.home_airport,
            "country": user.country,
            "holiday_calendar": user.holiday_calendar,
            "weather_tolerance": user.weather_tolerance,
            "nearby_airports": ", ".join(user.nearby_airports or []),
            "ignored_holidays": ", ".join(user.ignored_holidays or []),
            "extra_days_off": ", ".join(d.isoformat() for d in user.extra_days_off or []),
            "friday_evening_min_time": user.friday_evening_min_time.strftime("%H:%M"),
        }
        for key in BOOL_FIELDS:
            if getattr(user, key):
                form[key] = "on"
        windows = list(
            s.scalars(
                select(TravelWindow).where(TravelWindow.user_id == user.id).order_by(TravelWindow.start_date)
            )
        )
        trackers = list(
            s.scalars(
                select(Tracker)
                .where(Tracker.user_id == user.id, Tracker.active.is_(True))
                .order_by(Tracker.id)
            )
        )
    for i, w in enumerate([*windows, *([None] * EXTRA_ROWS)]):
        form[f"window_start_{i}"] = w.start_date.isoformat() if w else ""
        form[f"window_end_{i}"] = w.end_date.isoformat() if w else ""
    for i, t in enumerate([*trackers, *([None] * EXTRA_ROWS)]):
        form[f"tracker_dest_{i}"] = t.destination_code if t else ""
        form[f"tracker_min_{i}"] = str(t.min_stay_days) if t else ""
        form[f"tracker_max_{i}"] = str(t.max_stay_days) if t else ""
        form[f"tracker_priority_{i}"] = str(t.priority) if t else "2"
        form[f"tracker_price_{i}"] = f"{t.max_price:.0f}" if t and t.max_price is not None else ""
    return form


def row_count(form: Mapping[str, str], prefix: str) -> int:
    """How many numbered rows the form has (so templates can render them, plus re-rendering after errors)."""
    i = 0
    while f"{prefix}_{'start' if prefix == 'window' else 'dest'}_{i}" in form:
        i += 1
    return i
