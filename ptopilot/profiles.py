"""Load a traveler profile (user, travel windows, trackers) from YAML into the database.

    python -m ptopilot.profiles load profiles/me.yaml [--dry-run]
    python -m ptopilot.profiles invite friend@example.com

A stopgap until the web app's onboarding (Plan 6) exists. Loading is idempotent and keyed on email:
the user is created or updated, travel windows are replaced, trackers are matched by destination
code (updated in place, so their history and snoozes survive), and trackers missing from the file are
deactivated rather than deleted. The email is also added to `invites`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ptopilot.core.calendar import WorkCalendar
from ptopilot.core.geo import Geo, UnknownCodeError
from ptopilot.data import load_geo
from ptopilot.db.models import Invite, Tracker, TravelWindow, User
from ptopilot.db.session import make_engine
from ptopilot.settings import Settings

USER_FIELDS = {
    "home_airport": str,
    "country": str,
    "currency": str,
    "holiday_calendar": str,
    "pto_days_total": int,
    "pto_committed": int,
    "min_trip_days": int,
    "max_trip_days": int,
    "ideal_trip_days": int,
    "weather_tolerance": str,
    "max_stops_short": int,
    "max_stops_long": int,
    "allow_overnight_layover": bool,
    "friday_evening_departure": bool,
}
REQUIRED = ("email", "home_airport", "country", "holiday_calendar", "pto_days_total", "max_trip_days")
TOLERANCES = ("strict", "normal", "relaxed")
DEFAULT_MIN_TRIP_DAYS = 3  # matches the users.min_trip_days server default


@dataclass
class TrackerSpecRow:
    destination: str
    min_stay: int
    max_stay: int
    priority: int = 2
    max_price: Decimal | None = None


@dataclass
class Profile:
    email: str
    user: dict
    nearby_airports: list[str] = field(default_factory=list)
    extra_days_off: list[date] = field(default_factory=list)
    ignored_holidays: list[str] = field(default_factory=list)
    friday_evening_min_time: time | None = None
    windows: list[tuple[date, date]] = field(default_factory=list)
    trackers: list[TrackerSpecRow] = field(default_factory=list)


def _as_date(value, where: str, problems: list[str]) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        problems.append(f"{where}: {value!r} is not a YYYY-MM-DD date")
        return None


def parse_profile(data: dict, geo: Geo) -> Profile:
    """Validate a profile mapping. Raises ValueError listing every problem found."""
    problems: list[str] = []
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("invalid profile:\n  - the file must be a mapping of field: value pairs")
    for key in REQUIRED:
        if data.get(key) in (None, ""):
            problems.append(f"missing required field {key!r}")
    unknown = set(data) - set(USER_FIELDS) - {
        "email", "nearby_airports", "extra_days_off", "ignored_holidays",
        "friday_evening_min_time", "windows", "trackers",
    }  # fmt: skip
    if unknown:
        problems.append(f"unknown field(s) {sorted(unknown)}")

    user = {k: data[k] for k in USER_FIELDS if k in data}
    if user.get("ideal_trip_days", 0) is None:
        user.pop("ideal_trip_days")  # an explicit null means no preference, same as leaving it out
    for key, kind in USER_FIELDS.items():
        if key not in user:
            continue
        value = user[key]
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            problems.append(f"{key}: expected {kind.__name__}, got {value!r}")
            user.pop(key)

    def ok_int(key):
        return isinstance(user.get(key), int)

    email = str(data.get("email") or "")
    if email and not ("@" in email and "." in email.rsplit("@", 1)[-1]):
        problems.append(f"email: {email!r} is not an email address")
    if "country" in user and not (len(user["country"]) == 2 and user["country"].isalpha()):
        problems.append(f"country: expected a 2-letter code like US, got {user['country']!r}")
    if "currency" in user and not (len(user["currency"]) == 3 and user["currency"].isalpha()):
        problems.append(f"currency: expected a 3-letter code like USD, got {user['currency']!r}")
    if "weather_tolerance" in user and user["weather_tolerance"] not in TOLERANCES:
        problems.append(
            f"weather_tolerance: must be one of {list(TOLERANCES)}, got {user['weather_tolerance']!r}"
        )
    if ok_int("max_trip_days"):
        lo = user.get("min_trip_days", DEFAULT_MIN_TRIP_DAYS)
        if isinstance(lo, int) and not 0 < lo <= user["max_trip_days"]:
            problems.append(
                f"min_trip_days/max_trip_days: need 0 < min <= max, got {lo}..{user['max_trip_days']}"
            )
    if ok_int("ideal_trip_days"):
        lo, hi = user.get("min_trip_days", DEFAULT_MIN_TRIP_DAYS), user.get("max_trip_days")
        if isinstance(lo, int) and isinstance(hi, int) and not lo <= user["ideal_trip_days"] <= hi:
            problems.append(
                f"ideal_trip_days: {user['ideal_trip_days']} is outside your trip length {lo}..{hi}"
            )
    user.setdefault("ideal_trip_days", None)  # absent means no preference, and clears a stored one
    if ok_int("pto_days_total") and user["pto_days_total"] < 0:
        problems.append("pto_days_total: must be 0 or more")
    if ok_int("pto_committed"):
        if user["pto_committed"] < 0:
            problems.append("pto_committed: must be 0 or more")
        elif ok_int("pto_days_total") and user["pto_committed"] > user["pto_days_total"]:
            problems.append(
                f"pto_committed: {user['pto_committed']} is more than pto_days_total {user['pto_days_total']}"
            )
    for key in ("max_stops_short", "max_stops_long"):
        if ok_int(key) and user[key] < 0:
            problems.append(f"{key}: must be 0 or more")

    nearby = list(data.get("nearby_airports") or [])
    dupes = sorted({c for c in nearby if c == data.get("home_airport") or nearby.count(c) > 1})
    if dupes:
        problems.append(f"nearby_airports: {dupes} repeat the home airport or each other")

    for code in [data.get("home_airport"), *(data.get("nearby_airports") or [])]:
        if code:
            try:
                geo.airport(code)
            except UnknownCodeError:
                problems.append(f"unknown airport {code!r} (add it to ptopilot/data/geo.yaml)")

    extra = [_as_date(d, "extra_days_off", problems) for d in data.get("extra_days_off") or []]
    ignored = list(data.get("ignored_holidays") or [])
    if data.get("holiday_calendar"):
        try:
            WorkCalendar.from_code(data["holiday_calendar"], [d for d in extra if d], ignored)
        except ValueError as exc:
            problems.append(str(exc))

    min_time = None
    if data.get("friday_evening_min_time") is not None:
        try:
            min_time = time.fromisoformat(str(data["friday_evening_min_time"]))
        except ValueError:
            problems.append(f"friday_evening_min_time: {data['friday_evening_min_time']!r} is not HH:MM")

    windows = []
    for i, w in enumerate(data.get("windows") or []):
        if not isinstance(w, dict):
            problems.append(f"windows[{i}]: expected {{start: YYYY-MM-DD, end: YYYY-MM-DD}}, got {w!r}")
            continue
        start = _as_date(w.get("start"), f"windows[{i}].start", problems)
        end = _as_date(w.get("end"), f"windows[{i}].end", problems)
        if start and end:
            if end < start:
                problems.append(f"windows[{i}]: ends {end} before it starts {start}")
            windows.append((start, end))
    if not windows:
        problems.append("at least one travel window is required")

    trackers = []
    seen = set()
    for i, t in enumerate(data.get("trackers") or []):
        if not isinstance(t, dict):
            problems.append(
                f"trackers[{i}]: expected {{destination: CODE, min_stay: N, max_stay: N}}, got {t!r}"
            )
            continue
        code = t.get("destination")
        try:
            geo.destination(code)
        except UnknownCodeError:
            problems.append(f"trackers[{i}]: unknown destination {code!r} (add it to ptopilot/data/geo.yaml)")
            continue
        if code in seen:
            problems.append(f"trackers[{i}]: destination {code!r} listed twice")
        seen.add(code)
        lo, hi, prio = t.get("min_stay"), t.get("max_stay"), t.get("priority", 2)
        if not (isinstance(lo, int) and isinstance(hi, int) and 0 < lo <= hi):
            problems.append(f"trackers[{i}] ({code}): need 0 < min_stay <= max_stay, got {lo}..{hi}")
            continue
        if prio not in (1, 2, 3):
            problems.append(f"trackers[{i}] ({code}): priority must be 1, 2 or 3")
        price = t.get("max_price")
        max_price = None
        if price is not None:
            try:
                max_price = Decimal(str(price))
            except InvalidOperation:
                max_price = None
            if max_price is None or isinstance(price, bool) or not max_price.is_finite() or max_price <= 0:
                problems.append(f"trackers[{i}] ({code}): max_price must be a positive number, got {price!r}")
                continue
        trackers.append(TrackerSpecRow(code, lo, hi, prio, max_price))
    if not trackers and not any("trackers[" in p for p in problems):
        problems.append("at least one tracker is required")

    if problems:
        raise ValueError("invalid profile:\n  - " + "\n  - ".join(problems))
    return Profile(
        email=str(data["email"]).strip().lower(),
        user=user,
        nearby_airports=list(data.get("nearby_airports") or []),
        extra_days_off=[d for d in extra if d],
        ignored_holidays=ignored,
        friday_evening_min_time=min_time,
        windows=windows,
        trackers=trackers,
    )


def apply_profile(s: Session, p: Profile) -> dict[str, int | str]:
    """Upsert the profile in the given session (caller commits or rolls back). Returns a change summary."""
    summary: dict[str, int | str] = {}
    user = s.scalar(select(User).where(User.email == p.email))
    summary["user"] = "updated" if user else "created"
    if user is None:
        user = User(email=p.email)
        s.add(user)
    for key, value in p.user.items():
        setattr(user, key, value)
    user.nearby_airports = p.nearby_airports
    user.extra_days_off = p.extra_days_off
    user.ignored_holidays = p.ignored_holidays
    if p.friday_evening_min_time is not None:
        user.friday_evening_min_time = p.friday_evening_min_time
    s.flush()

    s.execute(delete(TravelWindow).where(TravelWindow.user_id == user.id))
    s.add_all(TravelWindow(user_id=user.id, start_date=a, end_date=b) for a, b in p.windows)
    summary["windows"] = len(p.windows)

    existing = {t.destination_code: t for t in s.scalars(select(Tracker).where(Tracker.user_id == user.id))}
    added = updated = 0
    for row in p.trackers:
        t = existing.pop(row.destination, None)
        if t is None:
            t = Tracker(user_id=user.id, destination_code=row.destination)
            s.add(t)
            added += 1
        else:
            updated += 1
        t.min_stay_days, t.max_stay_days = row.min_stay, row.max_stay
        t.priority, t.max_price, t.active = row.priority, row.max_price, True
    deactivated = 0
    for t in existing.values():
        if t.active:
            t.active = False
            deactivated += 1
    summary |= {"trackers_added": added, "trackers_updated": updated, "trackers_deactivated": deactivated}

    s.execute(insert(Invite).values(email=p.email).on_conflict_do_nothing())
    s.flush()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ptopilot.profiles")
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("load", help="create or update a traveler from a YAML profile")
    load.add_argument("path", type=Path)
    load.add_argument("--dry-run", action="store_true", help="validate and show changes without saving")
    invite = sub.add_parser("invite", help="allow an email address to sign in to the web app")
    invite.add_argument("email")
    args = parser.parse_args(argv)

    if args.command == "invite":
        email = args.email.strip().lower()
        if "@" not in email:
            print(f"not an email address: {args.email!r}", file=sys.stderr)
            return 2
        with Session(make_engine(Settings.from_env().database_url)) as s:
            s.execute(insert(Invite).values(email=email).on_conflict_do_nothing())
            s.commit()
        print(f"invited {email}")
        return 0

    engine = make_engine(Settings.from_env().database_url)
    try:
        profile = parse_profile(yaml.safe_load(args.path.read_text(encoding="utf-8")), load_geo(engine))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        with Session(engine) as s:
            summary = apply_profile(s, profile)
            if args.dry_run:
                s.rollback()
            else:
                s.commit()
    except SQLAlchemyError as exc:  # nothing was saved: the session rolls back on close
        print(
            f"database rejected the profile: {type(exc).__name__}: {str(exc).splitlines()[0]}",
            file=sys.stderr,
        )
        return 2
    verb = "would apply" if args.dry_run else "applied"
    print(f"{verb} profile for {profile.email}: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
