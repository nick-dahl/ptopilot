"""CLI: python -m ptopilot.pipeline run [--stage NAME ...] [--date YYYY-MM-DD] [--dry-run]

Exits 1 if any stage failed, so the GitHub Actions run shows red.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime

from ptopilot.notify.email import EmailError
from ptopilot.pipeline.context import build_context
from ptopilot.pipeline.health import send_report
from ptopilot.pipeline.runner import STAGES, run_pipeline
from ptopilot.settings import Settings

log = logging.getLogger("ptopilot.pipeline")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # httpx logs full request URLs at INFO, and SerpApi's api_key is a query parameter.
    # primp (fast-flights' HTTP client) logs every Google URL at INFO, which is just noise.
    for noisy in ("httpx", "primp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ptopilot.pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the daily scan")
    run.add_argument(
        "--stage", action="append", choices=list(STAGES), help="run only this stage (repeatable)"
    )
    run.add_argument("--date", type=date.fromisoformat, default=None, help="run date (default: today, UTC)")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="send no email: skip the health email; alerts only report what they would send",
    )
    args = parser.parse_args(argv)

    configure_logging()
    ctx = build_context(Settings.from_env(), args.date or datetime.now(UTC).date(), dry_run=args.dry_run)
    results = run_pipeline(ctx, args.stage)
    try:
        print(send_report(ctx, results))
    except EmailError as exc:
        log.error("health email not sent: %s", exc)
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
