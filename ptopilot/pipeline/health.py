"""The admin health email sent after every scan (spec §10)."""

from __future__ import annotations

import html
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.db.models import (
    AlertSend,
    Candidate,
    GemFare,
    PipelineRun,
    PriceObservation,
    RelatedCheck,
    SourceBudget,
)
from ptopilot.db.session import session_scope
from ptopilot.digest.render import date_range
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.freshness import day_freshness
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


def related_line(s: Session, day: date, results: Sequence[StageResult]) -> str:
    """This run's promising related fares; today's live checks and confirmations, re-runs included."""
    stage = next((r for r in results if r.stage == "related"), None)
    promising = stage.counts.get("promising", 0) if stage else 0
    rows = s.execute(select(RelatedCheck.confirmed).where(RelatedCheck.run_date == day)).scalars().all()
    return f"Related places: promising {promising}, checked {len(rows)}, confirmed {sum(rows)}"


def gems_line(s: Session, day: date, results: Sequence[StageResult]) -> str:
    """Gems this run published; today's priced rows and fares found, re-runs included."""
    stage = next((r for r in results if r.stage == "gems"), None)
    published = stage.counts.get("published", 0) if stage else 0
    rows = s.scalars(select(GemFare.status).where(GemFare.run_date == day)).all()
    return f"Hidden gems: published {published}, priced {len(rows)}, found {rows.count('found')}"


def duration(seconds: float | None) -> str:
    """'8s' under a minute, '2m05s' after; blank when the stage was never timed."""
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes}m{rest:02d}s"


HEALTH_EMAIL = "health_email"  # pipeline_runs marker (not a stage): the day's full health email went out


def _daily_email_due(s: Session, day: date, full_run: bool) -> bool:
    """True for a full run while no health email has been delivered for this date."""
    if not full_run:
        return False
    sent = s.scalar(
        select(PipelineRun.id)
        .where(PipelineRun.run_date == day, PipelineRun.stage == HEALTH_EMAIL, PipelineRun.status == "ok")
        .limit(1)
    )
    return sent is None


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _percent(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def freshness_lines(s: Session, day: date, results: Sequence[StageResult]) -> list[str]:
    """Today's live-price coverage, and (when live_verify ran) what this run checked and how Google did."""
    fresh = day_freshness(s, day)
    lines = [
        "Freshness:",
        f"  Fresh today: {fresh.fresh} of {fresh.in_horizon} in horizon ({len(fresh.not_fresh)} not yet)",
    ]
    live = next((r for r in results if r.stage == "live_verify" and r.status == "ok"), None)
    if live:
        c = live.counts
        lines.append(
            f"  Checks this run: {c.get('first_checks', 0)} first, {c.get('second_checks', 0)} second,"
            f" {c.get('audits', 0)} audit"
        )
        ok = c.get("google_flights_ok", 0)
        failed = c.get("google_flights_failed", 0) + c.get("google_flights_route_failed", 0)
        empty = _percent(c.get("no_flights", 0), ok)
        google = f"  Google: {_percent(failed, failed + ok)}% failed, {empty}% empty"
        if c.get("backoff_stopped", 0):
            google += f", back-off: stopped ({c['backoff_stopped']} left)"
        elif c.get("backoff_slowed", 0):
            google += ", back-off: slowed"
        lines.append(google)
    return lines


def yesterday_lines(s: Session, day: date) -> tuple[list[str], int]:
    """(report lines, stale-trip count) about the previous run date; only the first run reports them."""
    y = day_freshness(s, day - timedelta(days=1))
    lines = []
    if y.not_fresh:
        wait = f"longest: {_plural(y.longest_wait_days, 'day')}"
        lines.append(f"  {_plural(len(y.not_fresh), 'trip')} had no live price yesterday ({wait})")
    if y.unpriceable:
        lines.append(f"  Google can't price {_plural(len(y.unpriceable), 'trip')}")
    if y.open_jaw_no_budget:
        lines.append(f"  {_plural(len(y.open_jaw_no_budget), 'open-jaw trip')} waited for SerpApi budget")
    return lines, len(y.not_fresh)


def build_report(
    ctx: RunContext,
    results: Sequence[StageResult],
    interrupted: Sequence[PipelineRun] = (),
    full_run: bool = True,
) -> tuple[str, str]:
    """(subject, plain-text body); `interrupted` are stages an earlier, killed run left behind.

    `full_run` is False for a manual `--stage` run, which never carries yesterday's warning."""
    failed = [r.stage for r in results if r.status == "failed"]
    subject = f"ptopilot scan {ctx.run_date}: " + (f"FAILED ({', '.join(failed)})" if failed else "OK")
    with session_scope(ctx.engine) as s:
        fresh_lines = freshness_lines(s, ctx.run_date, results)
        old_lines, stale = (
            yesterday_lines(s, ctx.run_date) if _daily_email_due(s, ctx.run_date, full_run) else ([], 0)
        )
    if stale:
        subject += f" — {stale} trips stale"
    lines = [subject, "", "Stages:"]
    for r in results:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(r.counts.items()))
        tail = "  ".join(x for x in (duration(r.seconds), detail) if x)
        lines.append(f"  {r.stage:<12} {r.status:<8} {tail}".rstrip())
        if r.error:
            label = "reason" if r.status == "skipped" else "error"
            lines.append(f"  {'':<12} {label}: {r.error}")
    lines += [f"  Interrupted earlier: {row.run_date} {row.stage}" for row in interrupted]
    lines += ["", *fresh_lines, *old_lines]

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
            f"Alerts sent today: {s.scalar(select(func.count()).where(AlertSend.run_date == ctx.run_date))}",
            related_line(s, ctx.run_date, results),
            gems_line(s, ctx.run_date, results),
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


def interrupted_report(rows: Sequence[PipelineRun]) -> tuple[str, str]:
    """(subject, plain-text body) for a run GitHub killed before it could send its own report."""
    subject = f"ptopilot scan {rows[0].run_date}: INTERRUPTED ({', '.join(r.stage for r in rows)})"
    lines = [subject, "", "The run was stopped (cancelled or timed out) before it finished.", "", "Stages:"]
    lines += [f"  {row.run_date} {row.stage}" for row in rows]
    return subject, "\n".join(lines)


def _deliver(ctx: RunContext, subject: str, text: str) -> bool:
    """Send the email when configured and not a dry run; True when it went out (a failed send raises)."""
    if ctx.emailer and ctx.admin_email and not ctx.dry_run:
        ctx.emailer.send(ctx.admin_email, subject, f"<pre>{html.escape(text)}</pre>", text)
        return True
    return False


def _trouble(
    ctx: RunContext, results: Sequence[StageResult], interrupted: Sequence[PipelineRun], now: datetime
) -> bool:
    """Why a later run's report is worth an email: a failure, back-off, or unpriced trips at day's end."""
    if interrupted or any(r.status == "failed" for r in results):
        return True
    if any(r.counts.get("backoff_slowed") or r.counts.get("backoff_stopped") for r in results):
        return True
    if now.hour >= config.LAST_RUN_HOUR_UTC:
        with session_scope(ctx.engine) as s:
            return bool(day_freshness(s, ctx.run_date).not_fresh)
    return False


def send_report(
    ctx: RunContext,
    results: Sequence[StageResult],
    interrupted: Sequence[PipelineRun] = (),
    now: datetime | None = None,
    full_run: bool = True,
) -> str:
    """Email the report when configured and not a dry run; return the text.

    The first full run's email that actually goes out each day (it carries yesterday's warning) is recorded
    as a `health_email` marker; every other run emails only on trouble.
    """
    subject, text = build_report(ctx, results, interrupted, full_run)
    with session_scope(ctx.engine) as s:
        due = _daily_email_due(s, ctx.run_date, full_run)
    if (due or _trouble(ctx, results, interrupted, now or datetime.now(UTC))) and _deliver(
        ctx, subject, text
    ):
        if due:
            with session_scope(ctx.engine) as s:
                s.add(PipelineRun(run_date=ctx.run_date, stage=HEALTH_EMAIL, status="ok"))
    return text


def send_interrupted(ctx: RunContext, rows: Sequence[PipelineRun]) -> str:
    """Email the interrupted-run notice (same delivery rules as send_report); return the text."""
    subject, text = interrupted_report(rows)
    _deliver(ctx, subject, text)
    return text
