"""Trip shapes: realistic (depart, return) date pairs anchored on weekends and holidays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ptopilot.core.calendar import ONE_DAY, WorkCalendar


@dataclass(frozen=True)
class TripShape:
    depart_date: date
    return_date: date
    pto_cost: int
    evening_departure: bool = False
    days_off: tuple[str, ...] = ()

    @property
    def days_away(self) -> int:
        return (self.return_date - self.depart_date).days + 1

    @property
    def efficiency(self) -> float:
        return self.days_away / max(self.pto_cost, 0.5)


def is_departure_day(cal: WorkCalendar, d: date) -> bool:
    """First day of an off-block (e.g. Saturday), or the last workday before one (e.g. Friday)."""
    if cal.is_workday(d):
        return not cal.is_workday(d + ONE_DAY)
    return cal.is_workday(d - ONE_DAY)


def is_return_day(cal: WorkCalendar, d: date) -> bool:
    """Last day of an off-block (e.g. Sunday), or the first workday after one (e.g. Monday)."""
    if cal.is_workday(d):
        return not cal.is_workday(d - ONE_DAY)
    return cal.is_workday(d + ONE_DAY)


def generate_shapes(
    cal: WorkCalendar,
    window_start: date,
    window_end: date,
    max_days_away: int,
    friday_evening: bool = False,
    slack_days: int = 2,
) -> list[TripShape]:
    """All natural trip shapes whose depart and return fall in the window (± slack_days).

    With friday_evening, every shape departing on a workday also gets a variant that
    leaves after work that day: one less PTO day, evening_departure=True.
    """
    if window_end < window_start:
        raise ValueError(f"Window ends before it starts: {window_start} > {window_end}")
    first = window_start - slack_days * ONE_DAY
    last = window_end + slack_days * ONE_DAY
    days = [first + i * ONE_DAY for i in range((last - first).days + 1)]
    departs = [d for d in days if is_departure_day(cal, d)]
    returns = [d for d in days if is_return_day(cal, d)]

    shapes: list[TripShape] = []
    for dep in departs:
        for ret in returns:
            if ret <= dep:
                continue
            if (ret - dep).days + 1 > max_days_away:
                break
            pto = cal.pto_cost(dep, ret)
            days_off = cal.weekday_days_off(dep, ret)
            shapes.append(TripShape(dep, ret, pto, False, days_off))
            if friday_evening and cal.is_workday(dep):
                shapes.append(TripShape(dep, ret, pto - 1, True, days_off))
    return shapes
