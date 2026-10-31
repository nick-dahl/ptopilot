"""Stage `photos`: cover photos for the places in use, looked up here so no web request waits on Wikipedia.

A place an active tracker or an accepted related link uses, with no photo row yet (or a `none` row older
than PHOTO_RETRY_DAYS), gets its Wikipedia lead image looked up: at most PHOTO_LOOKUPS_PER_RUN a run.
Built-in places have hand-picked photos in geo.yaml and are never looked up. Hidden gems issued to anyone
(and not retired) join as `gem-{slug}`, looked up by the gem's name and country, unless the gem has its
own photo block, which wins as a built-in's does. A lookup that can't reach
Wikimedia stores nothing, so the place is tried again next run, and stops this run's lookups: the rest are
counted as skipped rather than each waiting out the timeout. The stage itself never fails the scan.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ptopilot import config
from ptopilot.core.airports import AirportCatalog
from ptopilot.core.geo import UnknownCodeError
from ptopilot.data import load_geo
from ptopilot.db.models import GemIssue, PlacePhotoRow, RelatedLink, Tracker
from ptopilot.db.session import session_scope
from ptopilot.gems import approved, load_catalogue
from ptopilot.photos import PhotoUnavailable, builtin_photos, fetch_photo
from ptopilot.pipeline.context import RunContext, StageSkipped

log = logging.getLogger(__name__)

COUNTS = ("looked_up", "found", "none", "failed", "skipped")


def _gem_places(s: Session) -> dict[str, tuple[str, str]]:
    """(name, country name) of each issued, approved gem without its own photo, by its `gem-{slug}` code."""
    try:
        gems = approved(load_catalogue())
    except ValueError:  # an invalid catalogue costs the gems their photos, never the other places
        log.exception("photo lookup: the gem catalogue is invalid")
        return {}
    issued = set(s.scalars(select(GemIssue.gem_slug).distinct()))
    return {g.code: (g.name, g.country_name) for g in gems if g.slug in issued and g.photo is None}


def _due(s: Session, ctx: RunContext) -> list[str]:
    """Places in use that need a lookup: never looked up first, then stale `none` rows; by code."""
    used = set(s.scalars(select(Tracker.destination_code).where(Tracker.active.is_(True))))
    used.update(s.scalars(select(RelatedLink.place_code).where(RelatedLink.status == "accepted")))
    used.update(_gem_places(s))
    used -= builtin_photos().keys()
    rows = {r.code: r for r in s.scalars(select(PlacePhotoRow).where(PlacePhotoRow.code.in_(used)))}
    stale = ctx.stamp() - timedelta(days=config.PHOTO_RETRY_DAYS)
    missing = sorted(code for code in used if code not in rows)
    retry = sorted(code for code, r in rows.items() if r.status == "none" and r.fetched_at < stale)
    return missing + retry


def run(ctx: RunContext) -> dict[str, int]:
    if ctx.http is None:
        raise StageSkipped("no HTTP client for Wikimedia")
    if ctx.dry_run:
        raise StageSkipped("dry run: no photo lookups")
    counts: Counter[str] = Counter(dict.fromkeys(COUNTS, 0))
    geo, catalog = load_geo(ctx.engine), AirportCatalog.load()
    with session_scope(ctx.engine) as s:
        due = _due(s, ctx)
        gem_places = _gem_places(s)
    batch = due[: config.PHOTO_LOOKUPS_PER_RUN]
    for i, code in enumerate(batch):
        if code in gem_places:
            name, country_name = gem_places[code]
        else:
            try:
                place = geo.destination(code)
            except UnknownCodeError:
                log.warning("photo lookup: unknown place %s", code)
                continue
            name, country_name = place.name, catalog.country_name(place.country)
        counts["looked_up"] += 1
        try:
            photo = fetch_photo(name, country_name, ctx.http)
        except PhotoUnavailable as exc:
            counts["failed"] += 1
            log.warning("photo lookup for %s failed: %s; skipping the rest this run", code, exc)
            counts["skipped"] += len(batch) - i - 1  # Wikimedia is down: the others would fail the same way
            break
        except Exception:  # a surprise in one answer never costs the other places (or the scan)
            counts["failed"] += 1
            log.exception("photo lookup for %s crashed", code)
            continue
        row = PlacePhotoRow(code=code, status="none", fetched_at=ctx.stamp())
        if photo is not None:
            row.status = "ok"
            row.image_url, row.width, row.height = photo.image_url, photo.width, photo.height
            row.author, row.licence, row.source_url = photo.author, photo.licence, photo.source_url
        with session_scope(ctx.engine) as s:
            s.merge(row)
        counts["found" if photo else "none"] += 1
    return dict(counts)
