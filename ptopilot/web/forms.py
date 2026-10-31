"""Profile form <-> the YAML-shaped profile dict, so the web form reuses profiles.parse_profile/apply_profile.

The form flattens lists into numbered fields (window_start_0, tracker_dest_1, ...). Blank rows are
ignored. Values that don't parse as numbers are passed through as text so parse_profile reports them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from sqlalchemy.orm import Session

from ptopilot.db.models import User

INT_FIELDS = (
    "pto_days_total", "pto_committed", "min_trip_days", "max_trip_days", "max_stops_short", "max_stops_long",
)  # fmt: skip
OPTIONAL_INT_FIELDS = ("ideal_trip_days",)  # blank means "no preference"
TEXT_FIELDS = ("home_airport", "country", "holiday_calendar", "weather_tolerance")
BOOL_FIELDS = ("allow_overnight_layover", "friday_evening_departure")
# The profile page's sections (each its own form) and the fields each one carries. "all" is the old
# single form: every field at once.
SECTIONS = {
    "airports": ("home_airport", "nearby_airports"),
    "time_off": ("pto_days_total", "holiday_calendar", "ignored_holidays", "extra_days_off"),
    "travel": (
        "min_trip_days", "max_trip_days", "ideal_trip_days", "weather_tolerance", "max_stops_short",
        "max_stops_long", "allow_overnight_layover", "friday_evening_departure", "friday_evening_min_time",
    ),
}  # fmt: skip
SECTIONS["all"] = (*SECTIONS["airports"], *SECTIONS["time_off"], *SECTIONS["travel"], "country")


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
    """Current values as form fields (empty defaults for a new traveler).

    Windows and the bucket list are not on the web form: the planner and destinations pages own them."""
    if user is None:
        form = {
            "weather_tolerance": "normal",
            "holiday_calendar": "US",
            "country": "US",
            "min_trip_days": "3",
            "max_stops_short": "1",
            "max_stops_long": "2",
            "friday_evening_min_time": "17:00",
            "ideal_trip_days": "",
        }
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
    return form


def merge_section(current: dict[str, str], submitted: Mapping[str, str]) -> dict[str, str]:
    """The submitted fields laid over the current ones, so one section can be saved on its own.

    A form leaves an unticked checkbox out entirely, so a switch missing from a named section
    (submitted["section"]) means off. Without a section name only the fields sent change."""
    fields = SECTIONS.get(submitted.get("section", ""), ())
    merged = {**current, **{k: v for k, v in submitted.items() if k != "section"}}
    for key in BOOL_FIELDS:
        if key in fields and key not in submitted:
            merged.pop(key, None)
    return merged


# parse_profile's problems are written for the YAML loader ("min_trip_days/max_trip_days: need ...").
# The web page shows each beside its field, in words for the person: (pattern, field, message).
_REQUIRED = {
    "home_airport": "Pick your home airport.",
    "country": "Pick a country.",
    "holiday_calendar": "Pick a holiday calendar.",
    "pto_days_total": "Enter how many PTO days you get a year.",
    "max_trip_days": "Set the longest trip you'd take.",
}
_LABELS = {
    "pto_days_total": "PTO days per year",
    "min_trip_days": "the shortest trip",
    "max_trip_days": "the longest trip",
    "ideal_trip_days": "the ideal trip",
    "max_stops_short": "stops",
    "max_stops_long": "stops",
}


def _names(items: str) -> str:
    """ "['A', 'B', 'C']" as "A, B and C"."""
    names = re.findall(r"'([^']*)'|\"([^\"]*)\"", items)
    names = [a or b for a, b in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _explain(problem: str, form: Mapping[str, str]) -> tuple[str | None, str]:
    if m := re.fullmatch(r"missing required field '(\w+)'", problem):
        return m[1], _REQUIRED.get(m[1], "This is required.")
    if m := re.fullmatch(r"unknown airport '([^']*)'.*", problem):
        home = (form.get("home_airport") or "").strip()
        field = "home_airport" if m[1] == home.upper() else "nearby_airports"
        if len(m[1]) <= 4:
            return field, f"We don't know an airport with the code {m[1]}. Pick one from the suggestions."
        typed = [home, *_list(form.get("nearby_airports", ""))]
        name = next((t for t in typed if t.upper() == m[1]), m[1].title())  # as typed, not shouted
        return field, f"We couldn't pick one airport for '{name}'. Pick one from the list, or type its code."
    if m := re.fullmatch(r"nearby_airports: (\[.*\]) repeat the home airport or each other", problem):
        names = _names(m[1])
        return "nearby_airports", f"{names} is already your home airport or listed twice."
    trip = r"min_trip_days/max_trip_days: need 0 < min <= max, got (-?\d+)\.\.(-?\d+)"
    if m := re.fullmatch(trip, problem):
        lo, hi = int(m[1]), int(m[2])
        if lo < 1:
            return "min_trip_days", "The shortest trip needs to be at least 1 day."
        return "max_trip_days", f"The shortest trip ({lo} days) can't be longer than the longest ({hi} days)."
    if m := re.fullmatch(r"ideal_trip_days: (\d+) is outside your trip length (\d+)\.\.(\d+)", problem):
        return "ideal_trip_days", f"Your ideal trip ({m[1]} days) has to fall between {m[2]} and {m[3]} days."
    if m := re.fullmatch(r"(\w+): expected int, got (.*)", problem):
        return m[1], f"Enter a whole number for {_LABELS.get(m[1], 'this')}, not {m[2]}."
    if m := re.fullmatch(r"(\w+): must be 0 or more", problem):
        label = _LABELS.get(m[1], "this")
        return m[1], f"{label[0].upper()}{label[1:]} can't be below 0."
    if problem.startswith("weather_tolerance:"):
        return "weather_tolerance", "Pick one of the weather choices."
    if m := re.fullmatch(r"country: expected a 2-letter code like US, got (.*)", problem):
        return "country", f"The country needs a 2-letter code like US, not {m[1]}."
    if m := re.fullmatch(r"Unknown holiday calendar: '(.*)'", problem):
        return "holiday_calendar", f"We don't have a holiday calendar for {m[1]}."
    if m := re.fullmatch(r"Unknown holiday name\(s\) for calendar '(.*)': (\[.*\])", problem):
        one = "," not in m[2]
        is_not, them = ("isn't a holiday", "it") if one else ("aren't holidays", "them")
        return "ignored_holidays", (
            f"{_names(m[2])} {is_not} in the {m[1]} calendar. Remove {them} or pick another calendar."
        )
    if m := re.fullmatch(r"extra_days_off: (.*) is not a YYYY-MM-DD date", problem):
        return "extra_days_off", (
            f"Not a date: {m[1].strip(chr(39))}. Pick days on the calendar, or type them like 2027-12-24."
        )
    if m := re.fullmatch(r"friday_evening_min_time: (.*) is not HH:MM", problem):
        return "friday_evening_min_time", f"Not a time: {m[1].strip(chr(39))}. Use one like 17:30."
    field, _, rest = problem.partition(": ")
    if rest and field in SECTIONS["all"]:
        return field, rest[0].upper() + rest[1:].rstrip(".") + "."
    return None, problem[0].upper() + problem[1:].rstrip(".") + "."


def explain_errors(problems: list[str], form: Mapping[str, str]) -> list[dict[str, str | None]]:
    """parse_profile's problems as [{"field": the form field it belongs beside (or None), "message"}]."""
    return [dict(zip(("field", "message"), _explain(p, form), strict=True)) for p in problems]
