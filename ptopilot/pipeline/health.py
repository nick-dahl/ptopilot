"""The admin health email sent after every scan (spec §10)."""

from __future__ import annotations

import html
from collections import Counter
from collections.abc import Sequence
from datetime import date, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.db.models import Candidate, PriceObservation, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.digest.render import date_range
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import month_of, start_of
from ptopilot.pipeline.runner import StageResult

AUDITED = ("google_flights", "serpapi")


def _pairs(s: Session, first: date, last: date) -> list[tuple[tuple, float, float]]:
    """(trip, fast-flights cheapest, SerpApi cheapest) for each trip both priced on the same day."""
    cheapest: dict[tuple, dict[str, float]] = {}
    rows = s.scalars(
        select(PriceObservation).where(
            PriceObservation.verified.is_(True),
            PriceObservation.source.in_(AUDITED),
            PriceObservation.observed_at >= start_of(first),
            PriceObservation.observed_at < start_of(last + timedelta(days=1)),
        )
    )
    for o in rows:
        key = (o.origin, o.dest_airport, o.return_airport, o.depart_date, o.return_date, o.observed_at.date())
        by_source = cheapest.setdefault(key, {})
        by_source[o.source] = min(float(o.price), by_source.get(o.source, float("inf")))
    return [(key, p["google_flights"], p["serpapi"]) for key, p in cheapest.items() if len(p) == 2]


def _tally(pairs: list[tuple[tuple, float, float]]) -> str:
    gaps = [ff - serp for _, ff, serp in pairs]
    equal = sum(1 for g in gaps if abs(g) <= config.AUDIT_EQUAL_USD)
    pricier = sum(1 for g in gaps if g > config.AUDIT_EQUAL_USD)
    return f"{len(pairs)} trips, cheaper {len(pairs) - equal - pricier}, equal {equal}, pricier {pricier}"


def _signed(dollars: float, pct: float) -> str:
    """+$137 (+23%): positive means fast-flights was pricier."""
    sign = "-" if round(dollars) < 0 else "+"
    return f"{sign}${abs(dollars):,.0f} ({pct:+.0f}%)"


def _gap(pairs: list[tuple[tuple, float, float]]) -> str:
    gap = median(ff - serp for _, ff, serp in pairs)
    pct = median(100 * (ff - serp) / serp for _, ff, serp in pairs)
    return f"median gap {_signed(gap, pct)}"


def audit_lines(s: Session, day: date) -> list[str]:
    """fast-flights vs SerpApi on the same trips: today, and over the last AUDIT_DAYS days."""
    title = "Audit (fast-flights vs SerpApi, today)"
    today = _pairs(s, day, day)
    if not today:
        lines = [f"{title}: no trips priced by both sources"]
    else:
        (origin, dest, _, depart, ret, _), ff, serp = max(today, key=lambda p: p[1] - p[2])
        if ff - serp > 0:
            worst = _signed(ff - serp, 100 * (ff - serp) / serp)
            trip = f"{origin}→{dest} {date_range(depart, ret)} (${ff:,.0f} vs ${serp:,.0f})"
            detail = f"  {_gap(today)}, worst {worst}: {trip}"
        else:
            detail = f"  {_gap(today)}; fast-flights was never pricier"
        lines = [f"{title}: {_tally(today)}", detail]
    recent = _pairs(s, day - timedelta(days=config.AUDIT_DAYS - 1), day)
    if recent:
        lines.append(f"Audit, last {config.AUDIT_DAYS} days: {_tally(recent)}; {_gap(recent)}")
    else:
        lines.append(f"Audit, last {config.AUDIT_DAYS} days: no trips priced by both sources")
    return lines


def build_report(ctx: RunContext, results: Sequence[StageResult]) -> tuple[str, str]:
    """(subject, plain-text body)."""
    failed = [r.stage for r in results if r.status == "failed"]
    subject = f"ptopilot scan {ctx.run_date}: " + (f"FAILED ({', '.join(failed)})" if failed else "OK")
    lines = [subject, "", "Stages:"]
    for r in results:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(r.counts.items()))
        lines.append(f"  {r.stage:<12} {r.status:<8} {detail}")
        if r.error:
            label = "reason" if r.status == "skipped" else "error"
            lines.append(f"  {'':<12} {label}: {r.error}")

    with session_scope(ctx.engine) as s:
        deals = Counter(
            dict(
                s.execute(
                    select(Candidate.deal_level, func.count())
                    .where(Candidate.run_date == ctx.run_date, Candidate.verdict != "ruled_out")
                    .group_by(Candidate.deal_level)
                ).all()
            )
        )
        verdicts = dict(
            s.execute(
                select(Candidate.verdict, func.count())
                .where(Candidate.run_date == ctx.run_date)
                .group_by(Candidate.verdict)
            ).all()
        )
        lines += [
            "",
            f"Candidates: great={deals['great']} good={deals['good']} none={deals['none']}"
            f" ruled_out={verdicts.get('ruled_out', 0)}",
            "",
            *audit_lines(s, ctx.run_date),
            "",
            "Budgets:",
        ]
        for source, caps in sorted(config.SOURCE_BUDGETS.items()):
            used = (
                s.scalar(
                    select(SourceBudget.calls_used).filter_by(source=source, period=month_of(ctx.run_date))
                )
                or 0
            )
            lines.append(
                f"  {source}: {used}/{caps['per_month']} this month ({caps['per_month'] - used} left)"
            )
    return subject, "\n".join(lines)


def send_report(ctx: RunContext, results: Sequence[StageResult]) -> str:
    """Email the report when configured and not a dry run; always return the text."""
    subject, text = build_report(ctx, results)
    if ctx.emailer and ctx.admin_email and not ctx.dry_run:
        ctx.emailer.send(ctx.admin_email, subject, f"<pre>{html.escape(text)}</pre>", text)
    return text
