"""Stage `alerts`: email rare, short-lived offers right away, after checking the flight home.

Runs last, on today's scored candidates. An offer is alerted only when it is a standout (great, verified,
confident and likely gone within days), its tracker is active, the user has had no alert today
(ALERTS_PER_DAY) and none for the same destination within ALERT_SAME_DESTINATION_DAYS. Before sending,
the one-way flight home is searched and judged like any itinerary: a miserable return skips the offer and
the user's next standout is tried; an unknown one (no source answered) still sends.

Return searches are capped at RETURN_CHECKS_PER_DAY a day for all users together, counted from today's
`live_checks` rows with purpose 'return' (so a re-run gets no fresh allowance). Every search is recorded
and charged to the source budgets the same way live_verify's are, dry runs included: the calls are real.
A dry run checks returns and reports what it would send, but sends nothing and records no alert.
Alerts never mark a candidate as sent: the next digest still carries the offer.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select

from ptopilot import config
from ptopilot.core.airports import AirportCatalog
from ptopilot.core.stats import Baseline
from ptopilot.db.models import AlertSend, LiveCheck, RouteQuery, Tracker
from ptopilot.db.session import session_scope
from ptopilot.digest.render import render_alert
from ptopilot.digest.select import DealCard, build_digests
from ptopilot.links import action_links
from ptopilot.notify.email import EmailError
from ptopilot.pipeline.context import RunContext, StageSkipped
from ptopilot.pipeline.live_verify import Budget, record_check
from ptopilot.pipeline.queries import load_baselines, rq_baseline_key
from ptopilot.pipeline.return_check import ReturnVerdict, check_return
from ptopilot.sources.base import ExactQuery, ExactResult, ExactSearchSource

log = logging.getLogger(__name__)
VERDICTS: tuple[ReturnVerdict, ...] = ("pass", "fail", "unknown")


class _Recorded:
    """A live source whose searches for the flight home are charged and recorded (purpose 'return')."""

    def __init__(self, ctx: RunContext, budget: Budget, rq: RouteQuery, source: ExactSearchSource):
        self._ctx, self._budget, self._rq, self._source = ctx, budget, rq, source
        self.name = source.name
        self.supports_open_jaw = source.supports_open_jaw

    def exact_search(self, query: ExactQuery) -> ExactResult:
        self._budget.charge(self.name)  # every attempted call counts, as in live_verify
        try:
            result = self._source.exact_search(query)
        except Exception as exc:
            record_check(self._ctx, self._rq, self.name, ok=False, error=str(exc), purpose="return")
            raise
        record_check(self._ctx, self._rq, self.name, ok=True, options=len(result.options), purpose="return")
        return result


def _return_verdict(
    ctx: RunContext,
    budget: Budget,
    rq: RouteQuery,
    card: DealCard,
    code: str,
    baseline: Baseline | None,
    catalog: AirportCatalog,
) -> tuple[ReturnVerdict, str | None]:
    sources = [_Recorded(ctx, budget, rq, src) for src in ctx.live_sources if budget.allows(src.name)]
    try:
        return check_return(
            sources,
            home=rq.origin,
            from_airport=rq.return_airport,
            depart=rq.return_date,
            destination=ctx.geo.destination(code),
            geo=ctx.geo,
            catalog=catalog,
            price=float(card.price),
            typical_median=baseline.median if baseline else None,
            confident=baseline is not None and baseline.confidence == "normal",
        )
    except Exception:  # an unexpected source error: the return is unknown, which still sends
        log.exception("return check crashed for candidate %s", card.candidate_id)
        return "unknown", None


def run(ctx: RunContext) -> dict[str, int]:
    if ctx.emailer is None and not ctx.dry_run:
        raise StageSkipped("no emailer configured")
    counts: Counter[str] = Counter(
        dict.fromkeys(
            ("standout", "sent", "held_daily_cap", "held_same_destination", "return_checks", "return_failed"),
            0,
        )
    )
    if ctx.dry_run:
        counts.update(dict.fromkeys(("would_send", *(f"would_send_return_{v}" for v in VERDICTS)), 0))
    digests = [
        d
        for d in build_digests(
            ctx.engine,
            ctx.geo,
            ctx.seasons,
            ctx.run_date,
            min_level="great",
            skip_sent=False,
            all_deals=True,
        )
        if d.run_date == ctx.run_date  # only today's scan; build_digests falls back to the latest one
    ]
    offers = {d.user_id: [c for c in d.deals if c.standout] for d in digests}
    counts["standout"] = sum(len(cards) for cards in offers.values())
    if not counts["standout"]:
        return dict(counts)

    since = ctx.run_date - timedelta(days=config.ALERT_SAME_DESTINATION_DAYS)
    with session_scope(ctx.engine) as s:
        alerts_today = Counter(
            dict(
                s.execute(
                    select(AlertSend.user_id, func.count())
                    .where(AlertSend.run_date == ctx.run_date)
                    .group_by(AlertSend.user_id)
                ).all()
            )
        )
        recent = {  # (user, destination) alerted within the rolling window
            (user_id, code)
            for user_id, code in s.execute(
                select(AlertSend.user_id, Tracker.destination_code)
                .join(Tracker, Tracker.id == AlertSend.tracker_id)
                .where(AlertSend.run_date > since, AlertSend.run_date <= ctx.run_date)
            )
        }
        tracker_ids = {c.tracker_id for cards in offers.values() for c in cards}
        codes = dict(
            s.execute(select(Tracker.id, Tracker.destination_code).where(Tracker.id.in_(tracker_ids))).all()
        )
        rq_ids = {c.route_query_id for cards in offers.values() for c in cards}
        rqs = {rq.id: rq for rq in s.scalars(select(RouteQuery).where(RouteQuery.id.in_(rq_ids)))}
        checks_used = s.scalar(
            select(func.count(func.distinct(LiveCheck.route_query_id))).where(
                LiveCheck.run_date == ctx.run_date, LiveCheck.purpose == "return"
            )
        )
        baselines = load_baselines(
            s, {(rq.origin, rq.dest_airport, rq.return_airport) for rq in rqs.values()}
        )

    checks_left = config.RETURN_CHECKS_PER_DAY - checks_used
    budget = Budget(ctx)
    catalog: AirportCatalog | None = None
    links = None
    if ctx.app_base_url and ctx.secret_key:  # snooze links need the web app and the shared key

        def links(card: DealCard) -> list[tuple[str, str]]:
            return action_links(
                ctx.app_base_url, ctx.secret_key, card.tracker_id, card.depart_date, card.return_date
            )

    for digest in digests:
        user = digest.user_id
        for card in offers[user]:  # best first: go-now, then price
            code = codes[card.tracker_id]
            if alerts_today[user] >= config.ALERTS_PER_DAY:
                counts["held_daily_cap"] += 1
                continue
            if (user, code) in recent:
                counts["held_same_destination"] += 1
                continue
            if checks_left <= 0:
                counts["held_return_check_cap"] += 1
                continue
            checks_left -= 1
            catalog = catalog or AirportCatalog.load()
            rq = rqs[card.route_query_id]
            baseline = baselines.get(rq_baseline_key(rq))
            verdict, note = _return_verdict(ctx, budget, rq, card, code, baseline, catalog)
            counts["return_checks"] += 1
            log.info(
                "alert candidate %s (user %s): return %s%s",
                card.candidate_id,
                user,
                verdict,
                f" ({note})" if note else "",
            )
            if ctx.dry_run:
                counts[f"would_send_return_{verdict}"] += 1
            if verdict == "fail":
                counts["return_failed"] += 1
                continue
            if ctx.dry_run:
                counts["would_send"] += 1
                alerts_today[user] += 1
                log.info("dry run: would alert user %s about candidate %s", user, card.candidate_id)
                continue
            subject, html, text = render_alert(card, links)
            try:
                ctx.emailer.send(digest.email, subject, html, text)
            except EmailError as exc:  # its message has addresses scrubbed; the others still go out
                counts["failed"] += 1
                log.error("alert for user %s not sent: %s", user, exc)
                break
            with session_scope(ctx.engine) as s:
                s.add(
                    AlertSend(
                        user_id=user,
                        tracker_id=card.tracker_id,
                        candidate_id=card.candidate_id,
                        run_date=ctx.run_date,
                    )
                )
            counts["sent"] += 1
            alerts_today[user] += 1
            recent.add((user, code))
    return dict(counts)
