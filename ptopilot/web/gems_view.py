"""What the hidden gems pages show (Plan 16, spec section 3.6): each gem as a card with the person's latest
fare, its fit pill, its cover photo and whether they already track the place."""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.core.airports import AirportCatalog, PlaceMatch
from ptopilot.core.geo import Palette, tint
from ptopilot.core.trip_styles import STYLES
from ptopilot.db.models import GemFare, GemIssue, Tracker, User
from ptopilot.destinations import destination_code
from ptopilot.gems import Gem
from ptopilot.photos import PlacePhoto, photos_for

GEM_COLOR = "#0e7490"  # a deep sea-teal: the cover's gradient while a gem has no photo
GEM_PALETTE = Palette(GEM_COLOR, tint(GEM_COLOR))


def fit_pill(fare: GemFare | None) -> tuple[str, str]:
    """The fit pill's copy and tone (green, orange or grey) for the person's latest fare check."""
    if fare is None or fare.status == "failed":  # not priced yet, or the check will be tried again
        return "Checking fares…", "grey"
    if fare.status != "found":
        return "No fares found lately", "grey"
    if fare.fits:
        month = calendar.month_name[fare.fit_month] if fare.fit_month else "travel"
        return f"Fits your {month} range · {fare.pto_cost} PTO", "green"
    return "outside your dates", "orange"


def months_label(months: Iterable[int]) -> str:
    """Month numbers as runs: (5, 6, 9) is "May–Jun, Sep"; a run may wrap the year ("Dec–Feb")."""
    wanted = sorted(set(months))
    if not wanted:
        return ""
    if len(wanted) == 12:
        return "all year"
    runs: list[list[int]] = []
    for m in wanted:
        if runs and m == runs[-1][-1] + 1:
            runs[-1].append(m)
        else:
            runs.append([m])
    if len(runs) > 1 and runs[0][0] == 1 and runs[-1][-1] == 12:
        runs[0] = runs.pop() + runs[0]
    abbr = calendar.month_abbr
    return ", ".join(abbr[r[0]] if len(r) == 1 else f"{abbr[r[0]]}–{abbr[r[-1]]}" for r in runs)


@dataclass(frozen=True)
class GemCard:
    gem: Gem
    issue: GemIssue | None
    fare: GemFare | None
    photo: PlacePhoto | None
    tracked: bool
    tracker_id: int | None = None

    palette = GEM_PALETTE

    @property
    def pill(self) -> tuple[str, str]:
        return fit_pill(self.fare)

    @property
    def priced(self) -> bool:
        """A fare is known: it always shows, fitting or not."""
        return self.fare is not None and self.fare.status == "found" and self.fare.price is not None

    @property
    def styles(self) -> list[str]:
        return [STYLES[s] for s in self.gem.styles]

    @property
    def best(self) -> str:
        return months_label(self.gem.best_months)

    @property
    def arrival(self) -> str:
        return _city(self.fare.airport) if self.fare else ""

    @property
    def home_from(self) -> str:
        """The city the fare flies home from, when it isn't the arrival (an open-jaw trip)."""
        if self.fare is None or self.fare.return_airport == self.fare.airport:
            return ""
        return _city(self.fare.return_airport)


def _city(code: str) -> str:
    found = AirportCatalog.load().get(code)
    return found.city if found else code


def gem_match(gem: Gem) -> PlaceMatch:
    """The gem's place as "Add a place" knows it: its first arrival airport."""
    catalog = AirportCatalog.load()
    airport = catalog.get(gem.airports[0])
    return PlaceMatch(airport, (), catalog.country_name(airport.country))


def track_airports(gem: Gem) -> list[str]:
    """Tracked as an ordinary round trip on the arrival airports (an open-jaw return isn't tracked)."""
    return list(gem.airports)


def latest_fares(s: Session, user_id: int, slugs: Iterable[str]) -> dict[str, GemFare]:
    """The person's newest answered fare check of each gem (`found` or `none`).

    A `failed` check is a transient miss that is tried again, so it never hides a fare already known; it
    shows only while a gem has no other row ("Checking fares…")."""
    rows = s.scalars(
        select(GemFare)
        .where(GemFare.user_id == user_id, GemFare.gem_slug.in_(set(slugs)))
        .order_by(GemFare.checked_at, GemFare.id)
    )
    out: dict[str, GemFare] = {}
    for row in rows:  # oldest first: later answered rows overwrite earlier ones
        if row.status != "failed" or out.get(row.gem_slug) is None or out[row.gem_slug].status == "failed":
            out[row.gem_slug] = row
    return out


def gem_photos(s: Session, gems: Iterable[Gem]) -> dict[str, PlacePhoto]:
    """Each gem's cover, by slug: its own hand-picked photo, else the one the photos stage found."""
    gems = list(gems)
    found = photos_for({g.code for g in gems if g.photo is None}, s)
    out = {g.slug: g.photo or found.get(g.code) for g in gems}
    return {slug: photo for slug, photo in out.items() if photo}


def trackers_for(s: Session, user: User, gems: Iterable[Gem]) -> dict[str, int]:
    """The person's active tracker of each gem's place, by gem slug."""
    active = {
        t.destination_code: t.id
        for t in s.scalars(select(Tracker).where(Tracker.user_id == user.id, Tracker.active.is_(True)))
    }
    out = {}
    for g in gems:
        code = destination_code(gem_match(g), track_airports(g), s)
        if code in active:
            out[g.slug] = active[code]
    return out


def cards(s: Session, user: User, entries: Sequence[tuple[Gem, GemIssue | None]]) -> list[GemCard]:
    gems = [g for g, _ in entries]
    fares = latest_fares(s, user.id, (g.slug for g in gems))
    photos = gem_photos(s, gems)
    tracked = trackers_for(s, user, gems)
    return [
        GemCard(g, i, fares.get(g.slug), photos.get(g.slug), g.slug in tracked, tracked.get(g.slug))
        for g, i in entries
    ]


def issues(s: Session, user: User) -> list[GemIssue]:
    """The person's issues, newest first."""
    return list(
        s.scalars(
            select(GemIssue)
            .where(GemIssue.user_id == user.id)
            .order_by(GemIssue.published_on.desc(), GemIssue.id.desc())
        )
    )


def feed(s: Session, user: User, catalogue: Sequence[Gem], limit: int | None = None) -> list[GemCard]:
    """The person's issues of approved gems, newest first (retired and unknown gems leave the feed)."""
    live = {g.slug: g for g in catalogue if g.status == "approved"}
    entries = [(live[i.gem_slug], i) for i in issues(s, user) if i.gem_slug in live]
    return cards(s, user, entries[:limit])


def can_open(s: Session, user: User, gem: Gem) -> bool:
    """Approved gems open for anyone signed in; retired ones only for people they were issued to."""
    if gem.status == "approved":
        return True
    if gem.status == "retired":
        return (
            s.scalar(select(GemIssue.id).where(GemIssue.user_id == user.id, GemIssue.gem_slug == gem.slug))
            is not None
        )
    return False


def is_new(issue: GemIssue | None, today) -> bool:
    return issue is not None and (today - issue.published_on).days < config.GEM_ISSUE_DAYS
