"""Work calendar: decides which days cost PTO."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import holidays

ONE_DAY = timedelta(days=1)
OBSERVED_SUFFIX = " (observed)"


@lru_cache(maxsize=512)
def _holiday_names(country: str, subdiv: str | None, year: int) -> dict[date, str]:
    return dict(holidays.country_holidays(country, subdiv=subdiv, years=year))


def _base_name(name: str) -> str:
    """Holiday name without "(observed)", case-folded for matching."""
    return name.removesuffix(OBSERVED_SUFFIX).casefold()


@lru_cache(maxsize=64)
def _known_names(country: str, subdiv: str | None) -> frozenset[str]:
    """Base names of every holiday this calendar has from last year through two years ahead."""
    this_year = date.today().year
    return frozenset(
        _base_name(n)
        for year in range(this_year - 1, this_year + 3)
        for raw in _holiday_names(country, subdiv, year).values()
        for n in raw.split("; ")
    )


def calendar_codes(current: str = "") -> list[str]:
    """Every country with a holiday calendar, plus the regional calendars (GB-ENG) of `current`'s country."""
    supported = holidays.list_supported_countries()
    country = current.strip().upper().partition("-")[0]
    countries = [code for code in supported if len(code) == 2]  # not the 3-letter aliases
    return sorted([*countries, *(f"{country}-{sub}" for sub in supported.get(country, ()))])


def upcoming_holiday_names(code: str, start: date, days: int = 366) -> list[str]:
    """Names of the holidays calendar `code` has in the `days` from `start`, soonest first, each once.

    "(observed)" days are folded into their holiday. An unknown calendar has none."""
    country, _, subdiv = code.strip().upper().partition("-")
    end = start + timedelta(days=days)
    try:
        found = {
            d: raw
            for year in range(start.year, end.year + 1)
            for d, raw in _holiday_names(country, subdiv or None, year).items()
            if start <= d < end
        }
    except NotImplementedError:
        return []
    names: dict[str, str] = {}
    for _, raw in sorted(found.items()):
        for name in raw.split("; "):
            name = name.removesuffix(OBSERVED_SUFFIX)
            names.setdefault(_base_name(name), name)
    return list(names.values())


@dataclass(frozen=True)
class WorkCalendar:
    country: str
    subdiv: str | None = None
    extra_days_off: frozenset[date] = frozenset()
    ignored_holidays: frozenset[str] = frozenset()  # case-folded base names; build via from_code

    @classmethod
    def from_code(
        cls,
        code: str,
        extra_days_off: Iterable[date] = (),
        ignored_holidays: Iterable[str] = (),
    ) -> WorkCalendar:
        """Build from a code like "US" or "GB-ENG" (country-subdivision)."""
        country, _, subdiv = code.strip().upper().partition("-")
        try:
            holidays.country_holidays(country, subdiv=subdiv or None)
        except NotImplementedError as exc:
            raise ValueError(f"Unknown holiday calendar: {code!r}") from exc
        ignored = {_base_name(n): n for n in ignored_holidays}
        unknown = [n for key, n in ignored.items() if key not in _known_names(country, subdiv or None)]
        if unknown:
            raise ValueError(f"Unknown holiday name(s) for calendar {code!r}: {unknown}")
        return cls(
            country=country,
            subdiv=subdiv or None,
            extra_days_off=frozenset(extra_days_off),
            ignored_holidays=frozenset(ignored),
        )

    def holiday_name(self, d: date) -> str | None:
        """Public-holiday name for d, or None. Ignored holidays (and their observed days) are skipped."""
        raw = _holiday_names(self.country, self.subdiv, d.year).get(d)
        if raw is None:
            return None
        kept = [n for n in raw.split("; ") if _base_name(n) not in self.ignored_holidays]
        return "; ".join(kept) or None

    def is_workday(self, d: date) -> bool:
        if d.weekday() >= 5 or d in self.extra_days_off:
            return False
        return self.holiday_name(d) is None

    def pto_cost(self, start: date, end: date) -> int:
        """Workdays in the inclusive range [start, end]."""
        return sum(1 for i in range((end - start).days + 1) if self.is_workday(start + i * ONE_DAY))

    def weekday_days_off(self, start: date, end: date) -> tuple[str, ...]:
        """Names of the weekday holidays / company days off in [start, end], in date order, de-duplicated."""
        names: list[str] = []
        for i in range((end - start).days + 1):
            d = start + i * ONE_DAY
            if d.weekday() >= 5:
                continue
            if d in self.extra_days_off:
                name = "Company day off"
            else:
                name = self.holiday_name(d)
            if name and name not in names:
                names.append(name)
        return tuple(names)
