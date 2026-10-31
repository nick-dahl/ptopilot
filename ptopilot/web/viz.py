"""Server-side drawing for the web app and digest: the "where this price sits" bar and the price trend.

No JavaScript needed: the bar is a set of percentages for CSS (or email table cells), and the trend is a small
inline SVG. Its points carry data-date/data-price, which static/chart.js reads for the hover tooltip.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median

from markupsafe import Markup

from ptopilot import config
from ptopilot.core.geo import Palette

BAR_SIGMAS = 3  # the bar spans median +/- 3 sigma; the typical band is median +/- 1 sigma
BAR_MIN, BAR_MAX = 2.0, 98.0  # keep the dot on the track
CHART_W, CHART_H, CHART_PAD = 800, 160, 10


@dataclass(frozen=True)
class BarGeometry:
    dot: float  # 0-100, left to right
    band_start: float
    band_end: float


@dataclass(frozen=True)
class TrendPoint:
    run_date: date
    price: Decimal


@dataclass(frozen=True)
class TrendChart:
    svg: Markup
    low: Decimal
    high: Decimal
    first: date
    last: date


def plain(price: Decimal) -> str:
    """A price as plain digits for a data attribute: 660.00 -> "660", 660.50 -> "660.5"."""
    return format(price.normalize(), "f")


def sigma_floor(median: float, sigma: float | None) -> float:
    """sigma, but never so small that the typical band collapses to a line."""
    return max(float(sigma or 0), config.SIGMA_FLOOR_FRACTION * float(median), 1.0)


def bar_geometry(price: Decimal, median: float | None, sigma: float | None) -> BarGeometry | None:
    if median is None:
        return None
    median = float(median)
    sigma = sigma_floor(median, sigma)
    lo, span = median - BAR_SIGMAS * sigma, 2 * BAR_SIGMAS * sigma

    def pos(x: float) -> float:
        return round(min(max((x - lo) / span * 100, BAR_MIN), BAR_MAX), 1)

    return BarGeometry(pos(float(price)), pos(median - sigma), pos(median + sigma))


def trend_chart(
    points: list[TrendPoint], band: tuple[Decimal, Decimal] | None, palette: Palette
) -> TrendChart | None:
    """A line of the cheapest price per scan day; missing days break the line. None below MIN_TREND_POINTS."""
    if len(points) < config.MIN_TREND_POINTS:
        return None
    points = sorted(points, key=lambda p: p.run_date)
    fares = [p.price for p in points]
    low_fare, high_fare = min(fares), max(fares)
    # The y-scale also spans the band, so it can be drawn; the labels report the fares only.
    low, high = min([low_fare, *(band or ())]), max([high_fare, *(band or ())])
    first, last = points[0].run_date, points[-1].run_date
    days = max((last - first).days, 1)
    spread = float(high - low) or 1.0

    def xy(p: TrendPoint) -> tuple[float, float]:
        x = CHART_PAD + (p.run_date - first).days / days * (CHART_W - 2 * CHART_PAD)
        y = CHART_H - CHART_PAD - float(p.price - low) / spread * (CHART_H - 2 * CHART_PAD)
        if high == low:
            y = CHART_H / 2
        return round(x, 1), round(y, 1)

    segments: list[list[TrendPoint]] = [[points[0]]]
    for prev, cur in zip(points, points[1:], strict=False):
        if (cur.run_date - prev.run_date).days > 1:
            segments.append([])
        segments[-1].append(cur)

    parts = [
        f'<svg class="trend" viewBox="0 0 {CHART_W} {CHART_H}" role="img" '
        f'aria-label="Cheapest fare from {first:%b %d} to {last:%b %d}">'
    ]
    if band:
        top = xy(TrendPoint(first, band[1]))[1]
        bottom = xy(TrendPoint(first, band[0]))[1]
        height = round(bottom - top, 1)
        parts.append(
            f'<rect class="trend-band" x="0" y="{top}" width="{CHART_W}" height="{height}" '
            f'fill="{palette.tint}"/>'
        )
    for seg in segments:
        if len(seg) == 1:
            # A lone point: a one-vertex polyline draws nothing. The latest point gets its own circle below.
            if seg[0] is not points[-1]:
                cx, cy = xy(seg[0])
                parts.append(f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="{palette.color}"/>')
            continue
        coords = " ".join(f"{x},{y}" for x, y in map(xy, seg))
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="{palette.color}" stroke-width="3" '
            'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        )
    cx, cy = xy(points[-1])
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="6" fill="{palette.color}" stroke="#fff" stroke-width="2"/>')
    # One marker per scan day for the tooltip (static/chart.js), hidden until it is the active point. A path,
    # not a circle, so the drawn circles stay countable on their own.
    for p in points:
        x, y = xy(p)
        parts.append(
            f'<path class="trend-pt" data-date="{p.run_date.isoformat()}" data-price="{plain(p.price)}" '
            f'd="M{x - 6},{y}a6,6 0 1,0 12,0a6,6 0 1,0 -12,0" fill="{palette.color}" stroke="#fff" '
            'stroke-width="2"/>'
        )
    parts.append("</svg>")
    return TrendChart(Markup("".join(parts)), low_fare, high_fare, first, last)


SPARK_W, SPARK_H, SPARK_PAD = 230, 60, 4
TREND_FLAT = 0.02  # within 2% of the usual price reads as steady


def sparkline(points: list[TrendPoint], width: int = SPARK_W, height: int = SPARK_H) -> str | None:
    """The hero's tiny trend: an SVG polyline `points` string, x from 0 to width, cheaper days lower.

    None below MIN_TREND_POINTS. Missing days are joined: at this size a break reads as a glitch.
    """
    if len(points) < config.MIN_TREND_POINTS:
        return None
    points = sorted(points, key=lambda p: p.run_date)
    first, last = points[0].run_date, points[-1].run_date
    days = max((last - first).days, 1)
    low, high = min(p.price for p in points), max(p.price for p in points)
    spread = float(high - low)

    def xy(p: TrendPoint) -> str:
        x = (p.run_date - first).days / days * width
        # SVG's y runs down: dearer days near the top, cheaper ones lower, so a falling fare falls.
        span = height - 2 * SPARK_PAD
        y = height / 2 if not spread else SPARK_PAD + float(high - p.price) / spread * span
        return f"{round(x, 1):g},{round(y, 1):g}"

    return " ".join(map(xy, points))


def trend_direction(points: list[TrendPoint]) -> str | None:
    """'down', 'up' or 'flat': the latest fare against the median of the days before it; None under 2 days."""
    if len(points) < 2:
        return None
    points = sorted(points, key=lambda p: p.run_date)
    usual = median(float(p.price) for p in points[:-1])
    change = float(points[-1].price) / usual - 1 if usual else 0.0
    if change <= -TREND_FLAT:
        return "down"
    if change >= TREND_FLAT:
        return "up"
    return "flat"
