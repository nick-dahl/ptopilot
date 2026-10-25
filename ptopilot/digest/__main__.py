"""CLI: python -m ptopilot.digest send [--date D] [--min-level good|great|none] [--preview DIR]

--preview writes each digest to DIR as HTML + text instead of emailing it (no database writes), which
is the way to tune the layout. --min-level none includes trips that aren't deals yet. Exits 1 if any
email failed to send, 2 if sending is requested but no emailer is configured.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from ptopilot.data import load_geo, load_seasons
from ptopilot.db.session import make_engine
from ptopilot.digest.select import LEVELS, build_digests
from ptopilot.digest.send import deliver
from ptopilot.links import action_links
from ptopilot.notify.email import ResendEmailer
from ptopilot.settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ptopilot.digest")
    sub = parser.add_subparsers(dest="command", required=True)
    send = sub.add_parser("send", help="build and send (or preview) the digests")
    send.add_argument(
        "--date", type=date.fromisoformat, default=None, help="as of this date (default: today, UTC)"
    )
    send.add_argument(
        "--min-level", choices=list(LEVELS), default="good", help="lowest deal level to include"
    )
    send.add_argument(
        "--preview", type=Path, default=None, help="write digests to this folder instead of sending"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if args.preview is None and not settings.resend_api_key:
        print(
            "RESEND_API_KEY is not set; use --preview DIR to write digests to files instead", file=sys.stderr
        )
        return 2
    today = args.date or datetime.now(UTC).date()
    engine = make_engine(settings.database_url)
    digests = build_digests(engine, load_geo(engine), load_seasons(engine), today, args.min_level)
    if args.min_level == "none" and args.preview is None:
        # Tuning digests include non-deals: send them to the admin only, never to other travelers.
        if not settings.admin_email:
            print("--min-level none sends only to ADMIN_EMAIL, which is not set", file=sys.stderr)
            return 2
        digests = [d for d in digests if d.email.lower() == settings.admin_email.strip().lower()]
    emailer = None if args.preview else ResendEmailer(settings.resend_api_key, settings.email_from)
    links = None
    if settings.app_base_url and settings.secret_key:  # snooze buttons need the web app and the shared key

        def links(card):
            return action_links(
                settings.app_base_url,
                settings.secret_key,
                card.tracker_id,
                card.depart_date,
                card.return_date,
            )

    counts = deliver(
        engine,
        digests,
        today,
        emailer=emailer,
        preview_dir=args.preview,
        links=links,
        base_url=settings.app_base_url or None,
    )
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing to send"
    print(f"digests for {today}: {len(digests)} built; {summary}")
    if args.preview:
        print(f"preview written to {args.preview.resolve()}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
