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
    return name.removesuffix(OBSERVED_SUFFIX)


@dataclass(frozen=True)
class WorkCalendar:
    country: str
    subdiv: str | None = None
    extra_days_off: frozenset[date] = frozenset()
    ignored_holidays: frozenset[str] = frozenset()

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
        return cls(
            country=country,
            subdiv=subdiv or None,
            extra_days_off=frozenset(extra_days_off),
            ignored_holidays=frozenset(ignored_holidays),
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
