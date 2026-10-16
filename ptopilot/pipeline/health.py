"""The admin health email sent after every scan (spec §10)."""

from __future__ import annotations

import html
from collections import Counter
from collections.abc import Sequence

from sqlalchemy import func, select

from ptopilot import config
from ptopilot.db.models import Candidate, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import month_of
from ptopilot.pipeline.runner import StageResult


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
                    .where(Candidate.run_date == ctx.run_date)
                    .group_by(Candidate.deal_level)
                ).all()
            )
        )
        lines += [
            "",
            f"Candidates: great={deals['great']} good={deals['good']} none={deals['none']}",
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
