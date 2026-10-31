"""Everything a pipeline run needs, built once and passed to every stage."""

from __future__ import annotations

import random
import time as time_module
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

import httpx
from sqlalchemy import Engine

from ptopilot.core.geo import Geo
from ptopilot.core.seasons import SeasonTable
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.session import make_engine
from ptopilot.notify.email import Emailer, ResendEmailer
from ptopilot.photos import http_client
from ptopilot.settings import Settings
from ptopilot.sources.base import ExactSearchSource, MonthScanSource
from ptopilot.sources.google_flights import GoogleFlightsSource
from ptopilot.sources.serpapi import SerpApiSource
from ptopilot.sources.travelpayouts import TravelpayoutsSource


class StageSkipped(Exception):
    """The stage has nothing it can do (e.g. a source isn't configured). Not a failure."""


class StageFailed(Exception):
    """The stage could not do its job."""


@dataclass
class RunContext:
    run_date: date
    engine: Engine
    geo: Geo
    seasons: SeasonTable
    month_source: MonthScanSource | None = None
    live_sources: Sequence[ExactSearchSource] = ()  # tried in order: primary first, then fallbacks
    emailer: Emailer | None = None
    admin_email: str = ""
    app_base_url: str = ""  # with secret_key, instant alerts carry snooze links (as the digest does)
    secret_key: str = ""
    dry_run: bool = False
    sleep: Callable[[float], None] = time_module.sleep
    rng: random.Random = field(default_factory=random.Random)
    clock: Callable[[], float] = time_module.monotonic  # seconds; live_verify's time budget
    http: httpx.Client | None = None  # Wikimedia, for the photos stage; None skips it (tests)

    def stamp(self) -> datetime:
        """observed_at for rows this run writes: now, or noon UTC on run_date when re-running a past day."""
        now = datetime.now(UTC)
        return now if now.date() == self.run_date else datetime.combine(self.run_date, time(12), UTC)


def build_context(settings: Settings, run_date: date, dry_run: bool = False) -> RunContext:
    live: list[ExactSearchSource] = [GoogleFlightsSource()]
    if settings.serpapi_key:
        live.append(SerpApiSource(settings.serpapi_key))
    engine = make_engine(settings.database_url)
    return RunContext(
        run_date=run_date,
        engine=engine,
        geo=load_geo(engine),  # built-ins plus places users added on the website
        seasons=load_seasons(engine),
        month_source=TravelpayoutsSource(settings.travelpayouts_token)
        if settings.travelpayouts_token
        else None,
        live_sources=live,
        emailer=ResendEmailer(settings.resend_api_key, settings.email_from)
        if settings.resend_api_key
        else None,
        admin_email=settings.admin_email,
        app_base_url=settings.app_base_url,
        secret_key=settings.secret_key,
        dry_run=dry_run,
        http=http_client(),
    )
