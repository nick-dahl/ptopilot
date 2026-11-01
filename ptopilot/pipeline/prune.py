"""Stage `prune`: deletes price observations past the retention rule (owner's rule, Plan 17).

Keep a trip's price history until 90 days after it departs, and nothing observed more than ~13 months
ago. Why: scoring and charts read at most ~60 days back, but a trip's own history matters until it
departs. Month-only rows (no exact depart date) count as departed once their whole month ended more than
90 days ago. Candidates that pointed at a deleted row keep their own price (FK is SET NULL).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, delete, func, or_, select

from ptopilot import config
from ptopilot.db.models import PriceObservation as PO
from ptopilot.db.session import session_scope
from ptopilot.pipeline.context import RunContext
from ptopilot.pipeline.queries import month_of, start_of


def run(ctx: RunContext) -> dict[str, int]:
    cutoff = ctx.run_date - timedelta(days=config.PRICE_KEEP_AFTER_DEPARTURE_DAYS)
    expired = or_(
        and_(PO.depart_date.is_not(None), PO.depart_date < cutoff),
        and_(PO.depart_date.is_(None), PO.month < month_of(cutoff)),
        PO.observed_at < start_of(ctx.run_date - timedelta(days=config.PRICE_KEEP_MAX_DAYS)),
    )
    with session_scope(ctx.engine) as s:
        if ctx.dry_run:
            return {"would_delete": s.scalar(select(func.count()).select_from(PO).where(expired)) or 0}
        return {"deleted": s.execute(delete(PO).where(expired)).rowcount}
