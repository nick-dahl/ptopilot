"""Render a Digest as an email: subject, HTML (inline styles, table layout for mail clients), plain text."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from ptopilot import config
from ptopilot.digest.select import DealCard, Digest
from ptopilot.plan_totals import YearTotals
from ptopilot.web.viz import BarGeometry, bar_geometry

LinkBuilder = Callable[[DealCard], list[tuple[str, str]]]

LEVEL_LABEL = {"great": "Great deal", "good": "Good deal", "none": "Tracking"}
TREND_ARROW = {"down": "↓", "up": "↑", "flat": "→", "new": "·"}


def money(value: Decimal | float | None, currency: str = "USD") -> str:
    if value is None:
        return "—"
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{value:,.0f}"


def day(d) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def date_range(start, end) -> str:
    """Mar 5–15, Feb 27–Mar 14, or Dec 28, 2027–Jan 4, 2028."""
    if start.year != end.year:
        return f"{start:%b} {start.day}, {start.year}–{end:%b} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{start:%b} {start.day}–{end:%b} {end.day}"
    return f"{start:%b} {start.day}–{end.day}"


def duration(minutes: int | None) -> str:
    if not minutes:
        return ""
    return f"{minutes // 60}h {minutes % 60:02d}m"


def clock(dt) -> str:
    if dt is None:
        return ""
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d}{'am' if dt.hour < 12 else 'pm'}"


def checked_ago(observed: datetime | None, now: datetime) -> str:
    if observed is None:
        return ""
    hours = int((now - observed).total_seconds() // 3600)
    if hours < 1:
        return "checked under an hour ago"
    if hours < 48:
        return f"checked {hours} hour{'s' if hours != 1 else ''} ago"
    return f"checked {hours // 24} days ago"


def stops(n: int | None) -> str:
    if n is None:
        return ""
    return "nonstop" if n == 0 else f"{n} stop{'s' if n != 1 else ''}"


_env = Environment(
    loader=PackageLoader("ptopilot.digest", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False, default_for_string=True),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters.update(money=money, day=day, dates=date_range, duration=duration, clock=clock, stops=stops)


DAY_NAMES = ("Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays")


def schedule(weekdays) -> str:
    """(0, 3) -> "Mondays and Thursdays"."""
    names = [DAY_NAMES[d] for d in sorted(weekdays)]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


BAR_DOT_WIDTH = 3.0  # percent of the bar


def bar_cells(bar: BarGeometry) -> list[tuple[float, str]]:
    """The price bar as table cells for email: (width %, "track" | "band" | "dot"), left to right."""
    d0 = min(max(bar.dot - BAR_DOT_WIDTH / 2, 0.0), 100 - BAR_DOT_WIDTH)
    d1 = d0 + BAR_DOT_WIDTH
    edges = sorted({0.0, bar.band_start, bar.band_end, d0, d1, 100.0})
    cells: list[tuple[float, str]] = []
    for lo, hi in zip(edges, edges[1:], strict=False):
        mid = (lo + hi) / 2
        kind = "dot" if d0 <= mid <= d1 else "band" if bar.band_start <= mid <= bar.band_end else "track"
        if cells and cells[-1][1] == kind:
            cells[-1] = (round(cells[-1][0] + hi - lo, 1), kind)
        else:
            cells.append((round(hi - lo, 1), kind))
    return cells


def banner_text(t: YearTotals) -> str:
    """2027: 5 booked · 15 planned · 4 PTO left (or "5 PTO over" when planned trips outgrow the year)."""
    tail = f"{t.left} PTO left" if t.left >= 0 else f"{-t.left} PTO over"
    return f"{t.year}: {t.booked} booked · {t.planned} planned · {tail}"


def subject(digest: Digest) -> str:
    if digest.quiet:
        return "ptopilot: a quiet week for your trips"
    top = digest.deals[0]
    count = len(digest.deals)
    lead = f"{top.destination} {money(top.price, top.currency)}"
    if top.pct_below and top.pct_below > 0:
        lead += f" ({top.pct_below}% below typical)"
    more = f" + {count - 1} more" if count > 1 else ""
    return f"ptopilot: {lead}{more}"


def render(
    digest: Digest,
    now: datetime | None = None,
    links: LinkBuilder | None = None,
    base_url: str | None = None,
) -> tuple[str, str, str]:
    """(subject, html, text). `links` adds snooze buttons (label, url) to the lead deal; `base_url` (the web
    app) makes the other deals link to their destination pages."""
    now = now or datetime.now(UTC)
    bars = {
        d.candidate_id: bar_cells(bar)
        for d in digest.deals
        if d.typical and (bar := bar_geometry(d.price, float(d.typical), d.sigma))
    }
    context = {
        "actions": {d.candidate_id: links(d) if links else [] for d in digest.deals},
        "bars": bars,
        "base_url": (base_url or "").rstrip("/"),
        "preheader": subject(digest).removeprefix("ptopilot: "),
        "schedule": schedule(config.DIGEST_WEEKDAYS),
        "digest": digest,
        "banner": banner_text(digest.banner) if digest.banner else None,
        "levels": LEVEL_LABEL,
        "arrows": TREND_ARROW,
        "checked": {d.candidate_id: checked_ago(d.observed_at, now) for d in digest.deals},
    }
    html = _env.get_template("digest.html.j2").render(**context)
    text = _env.get_template("digest.txt.j2").render(**context)
    return subject(digest), html, text
