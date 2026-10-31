"""Stage `photos`: cover photos for places in use, found outside web requests (fake transport; no network).

Built-in places have hand-picked photos in geo.yaml and are never looked up.
"""

from datetime import UTC, datetime, time, timedelta

import httpx
import pytest
from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import Destination, PlacePhotoRow, RelatedLink
from ptopilot.db.session import session_scope
from ptopilot.photos import http_client
from ptopilot.pipeline import photos, runner
from ptopilot.pipeline.context import StageSkipped
from tests.pipeline.conftest import RUN, add_tracker, add_user

NOON = datetime.combine(RUN, time(12), UTC)  # the stage's stamp for this run date
COMMONS = "https://upload.wikimedia.org/wikipedia/commons"


def add_place(engine, code, name, airport):
    with session_scope(engine) as s:
        s.add(Destination(code=code, name=name, kind="city", airports=[airport]))


def add_row(engine, code, status, age_days, image_url=None):
    with session_scope(engine) as s:
        s.add(
            PlacePhotoRow(
                code=code,
                status=status,
                image_url=image_url,
                fetched_at=NOON - timedelta(days=age_days),
            )
        )


def rows(engine) -> dict[str, PlacePhotoRow]:
    with session_scope(engine) as s:
        found = {r.code: r for r in s.scalars(select(PlacePhotoRow))}
        s.expunge_all()
    return found


def wikimedia(found: set[str], seen: list[str] | None = None, fail: Exception | None = None):
    """Every page in `found` has a JPEG lead image; every other title is a 404."""

    def handle(request: httpx.Request) -> httpx.Response:
        if fail is not None:
            raise fail
        if request.url.host == "en.wikipedia.org":
            title = request.url.path.rsplit("/", 1)[-1].replace("_", " ")
            if seen is not None:
                seen.append(title)
            if title not in found:
                return httpx.Response(404, json={})
            file = title.replace(" ", "_") + ".jpg"
            source = f"{COMMONS}/a/ab/{file}"
            return httpx.Response(
                200, json={"originalimage": {"source": source, "width": 2560, "height": 1600}}
            )
        name = request.url.params["titles"].removeprefix("File:")
        info = {
            "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}",
            "extmetadata": {"Artist": {"value": "Ana"}, "LicenseShortName": {"value": "CC BY 4.0"}},
        }
        return httpx.Response(200, json={"query": {"pages": {"1": {"imageinfo": [info]}}}})

    return http_client(transport=httpx.MockTransport(handle))


@pytest.fixture
def places(clean_engine):
    """Barcelona, Rome, Oslo and Nice tracked; Bergen an accepted related place; Lisbon built in."""
    uid = add_user(clean_engine)
    for code, name, airport in [
        ("BCN_ES", "Barcelona", "BCN"),
        ("FCO_IT", "Rome", "FCO"),
        ("OSL_NO", "Oslo", "OSL"),
        ("NCE_FR", "Nice", "NCE"),
        ("BGO_NO", "Bergen", "BGO"),
        ("ATH_GR", "Athens", "ATH"),  # added, but nobody tracks it
    ]:
        add_place(clean_engine, code, name, airport)
    tid = None
    for code in ("BCN_ES", "FCO_IT", "OSL_NO", "NCE_FR", "LIS"):
        tid = add_tracker(clean_engine, uid, code)
    with session_scope(clean_engine) as s:
        s.add(RelatedLink(user_id=uid, tracker_id=tid, airport="BGO", place_code="BGO_NO", status="accepted"))
    return uid


def test_the_stage_fills_missing_places_and_retries_none_after_30_days(make_ctx, clean_engine, places):
    add_row(clean_engine, "FCO_IT", "none", 31)  # stale: retried
    add_row(clean_engine, "OSL_NO", "none", 5)  # recent: left alone
    add_row(clean_engine, "NCE_FR", "ok", 400, f"{COMMONS}/thumb/x/xy/Nice.jpg/1280px-Nice.jpg")  # kept
    seen: list[str] = []
    ctx = make_ctx(http=wikimedia({"Barcelona", "Rome"}, seen))

    counts = photos.run(ctx)

    assert counts == {"looked_up": 3, "found": 2, "none": 1, "failed": 0}
    assert "Oslo" not in seen and "Nice" not in seen and "Lisbon" not in seen and "Athens" not in seen
    assert "Bergen, Norway" in seen  # the name alone first, then with the country
    found = rows(clean_engine)
    assert found["BCN_ES"].status == "ok" and found["BCN_ES"].author == "Ana"
    assert found["BCN_ES"].image_url == f"{COMMONS}/thumb/a/ab/Barcelona.jpg/1280px-Barcelona.jpg"
    assert (found["BCN_ES"].width, found["BCN_ES"].height, found["BCN_ES"].licence) == (
        1280,
        800,
        "CC BY 4.0",
    )
    assert found["BCN_ES"].fetched_at == NOON
    assert found["FCO_IT"].status == "ok" and found["FCO_IT"].fetched_at == NOON
    assert found["BGO_NO"].status == "none" and found["BGO_NO"].image_url is None
    assert found["OSL_NO"].fetched_at == NOON - timedelta(days=5)
    assert found["NCE_FR"].status == "ok" and "LIS" not in found

    assert photos.run(make_ctx(http=wikimedia(set()))) == {"looked_up": 0, "found": 0, "none": 0, "failed": 0}


def test_at_most_a_set_number_of_places_are_looked_up_per_run(make_ctx, clean_engine, places, monkeypatch):
    assert config.PHOTO_LOOKUPS_PER_RUN == 20
    monkeypatch.setattr(config, "PHOTO_LOOKUPS_PER_RUN", 2)
    counts = photos.run(make_ctx(http=wikimedia({"Barcelona"})))
    assert counts["looked_up"] == 2 and len(rows(clean_engine)) == 2


def test_a_photo_failure_never_fails_the_scan(make_ctx, clean_engine, places):
    ctx = make_ctx(http=wikimedia(set(), fail=httpx.ConnectError("offline")))
    results = {r.stage: r for r in runner.run_pipeline(ctx, ["photos", "alerts"])}
    assert results["photos"].status == "ok"
    assert results["photos"].counts == {"looked_up": 5, "found": 0, "none": 0, "failed": 5}
    assert results["alerts"].status != "not_run"
    assert rows(clean_engine) == {}  # an outage stores nothing, so every place is tried again tomorrow
    assert "photos" in runner.CONTINUE_ON_FAILURE
    assert list(runner.STAGES).index("related") < list(runner.STAGES).index("photos")
    assert list(runner.STAGES).index("photos") < list(runner.STAGES).index("alerts")


def test_a_crash_in_one_lookup_is_counted_and_the_rest_go_on(make_ctx, clean_engine, places, monkeypatch):
    real = photos.fetch_photo

    def flaky(name, country, client):
        if name == "Barcelona":
            raise RuntimeError("bad JSON")
        return real(name, country, client)

    monkeypatch.setattr(photos, "fetch_photo", flaky)
    counts = photos.run(make_ctx(http=wikimedia({"Rome"})))
    assert counts == {"looked_up": 5, "found": 1, "none": 3, "failed": 1}
    assert "BCN_ES" not in rows(clean_engine)


def test_without_a_client_or_on_a_dry_run_the_stage_is_skipped(make_ctx, places):
    with pytest.raises(StageSkipped):
        photos.run(make_ctx())
    with pytest.raises(StageSkipped):
        photos.run(make_ctx(http=wikimedia({"Barcelona"}), dry_run=True))
