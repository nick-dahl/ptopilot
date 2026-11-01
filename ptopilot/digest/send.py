"""Send (or preview) digests and record what went out (spec §8)."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from sqlalchemy import Engine, update
from sqlalchemy.exc import SQLAlchemyError

from ptopilot import config
from ptopilot.db.models import Candidate, DigestSend
from ptopilot.db.session import session_scope
from ptopilot.digest.render import LinkBuilder, render
from ptopilot.digest.select import Digest
from ptopilot.notify.email import Emailer

log = logging.getLogger(__name__)
REAL_DEALS = frozenset({"good", "great"})


def deliver(
    engine: Engine,
    digests: Sequence[Digest],
    today: date,
    emailer: Emailer | None = None,
    preview_dir: Path | None = None,
    links: LinkBuilder | None = None,
    base_url: str | None = None,
) -> Counter[str]:
    """Send each digest (or write it to preview_dir), recording sends.

    A digest with no deals ("quiet") goes out only on QUIET_DIGEST_WEEKDAY. Preview never touches the
    database or the network. One person's failure never stops the others: a render or email error counts
    "failed" (nothing sent); a database error while recording a sent digest is retried once, then counts
    "record_failed" (the email did go out, so it still counts as sent, but the deals may repeat).
    """
    counts: Counter[str] = Counter()
    for digest in digests:
        if digest.quiet and today.weekday() != config.QUIET_DIGEST_WEEKDAY and preview_dir is None:
            counts["quiet_skipped"] += 1
            continue
        if preview_dir is None and emailer is None:  # a setup mistake, not one person's failure
            raise ValueError("an emailer is required unless previewing (set RESEND_API_KEY)")
        try:
            subject, html, text = render(digest, links=links, base_url=base_url)
            if preview_dir is not None:
                preview_dir.mkdir(parents=True, exist_ok=True)
                stem = f"digest-{digest.user_id}-{digest.run_date}"
                (preview_dir / f"{stem}.html").write_text(html, encoding="utf-8")
                (preview_dir / f"{stem}.txt").write_text(f"Subject: {subject}\n\n{text}", encoding="utf-8")
                counts["previewed"] += 1
                continue
            emailer.send(digest.email, subject, html, text)
        except Exception:  # one person's render/email problem must not stop the others
            counts["failed"] += 1
            log.exception("digest for user %s not sent", digest.user_id)
            continue
        # Only real deals count as "sent": tuning digests (min level none) mustn't hold back later deals.
        deals = [d for d in digest.deals if d.deal_level in REAL_DEALS]
        try:
            try:
                _record(engine, digest, deals)
            except SQLAlchemyError:  # one retry rides out a transient connection hiccup
                log.warning("recording digest for user %s failed; retrying once", digest.user_id)
                _record(engine, digest, deals)
        except SQLAlchemyError:
            counts["record_failed"] += 1
            log.exception(
                "digest for user %s was sent but not recorded; its deals may be sent again next time",
                digest.user_id,
            )
        counts["sent"] += 1
        counts["deals_sent"] += len(deals)
    return counts


def _record(engine: Engine, digest: Digest, deals: list) -> None:
    """Store the DigestSend row and mark its deals sent, in one transaction."""
    with session_scope(engine) as s:
        s.add(
            DigestSend(
                user_id=digest.user_id,
                items=[
                    {
                        "candidate_id": d.candidate_id,
                        "tracker_id": d.tracker_id,
                        "route_query_id": d.route_query_id,
                        "evening_departure": d.evening_departure,
                        "price": float(d.price),
                    }
                    for d in deals
                ],
            )
        )
        ids = [d.candidate_id for d in deals]
        if ids:
            s.execute(update(Candidate).where(Candidate.id.in_(ids)).values(state="sent"))
