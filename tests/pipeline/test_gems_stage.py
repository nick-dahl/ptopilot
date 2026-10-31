"""Stage `gems`: weekly publishing and free live fares for the newest gems (fake sources; no network).

The fixture catalogue (tests/fixtures/gems) has Lipnica Valley (LJU; best in May, June and September),
Høgvik Islands (into BOO, home from SVJ; its own photo) and a draft. The seeded user (ORD, open in June
2027, 15 PTO days, trips of 3..16 days, so 9 days away is the aim) has no styles, so their first issue is
the catalogue's first gem: Lipnica Valley.
"""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from ptopilot import config, gems
from ptopilot.db.models import GemFare, GemIssue
from ptopilot.db.session import session_scope
from ptopilot.pipeline import gems as stage
from ptopilot.pipeline import photos, runner
from tests.pipeline.conftest import (
    RUN,
    FakeLiveSource,
    FakeMonthSource,
    add_user,
    answering,
    failing,
    option,
    quote,
)
from tests.pipeline.test_photos_stage import wikimedia

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gems"
JUNE = date(2027, 6, 1)
TRIP = (date(2027, 6, 5), date(2027, 6, 12))  # 8 days away, 5 workdays
LIPNICA = "lipnica-valley"


@pytest.fixture(autouse=True)
def catalogue(monkeypatch):
    monkeypatch.setenv(gems.GEMS_DIR_ENV, str(FIXTURES))


def month(*quotes, airport="LJU", when=JUNE):
    return FakeMonthSource({("ORD", airport, when): list(quotes)})


def live(*options, open_jaw=False):
    return FakeLiveSource("google_flights", answering(*options), supports_open_jaw=open_jaw)


def fares(engine) -> list[GemFare]:
    with session_scope(engine) as s:
        rows = list(s.scalars(select(GemFare).order_by(GemFare.id)))
        s.expunge_all()
        return rows


def issues(engine) -> list[tuple[int, str, date]]:
    with session_scope(engine) as s:
        return [
            (i.user_id, i.gem_slug, i.published_on) for i in s.scalars(select(GemIssue).order_by(GemIssue.id))
        ]


def test_an_empty_catalogue_is_a_quiet_no_op(make_ctx, monkeypatch, tmp_path):
    monkeypatch.setenv(gems.GEMS_DIR_ENV, str(tmp_path))
    gf = live(option(500))
    ctx = make_ctx(month_source=month(quote("ORD", "LJU", *TRIP, 400)), live_sources=[gf])
    add_user(ctx.engine)

    counts = stage.run(ctx)

    assert set(counts.values()) == {0}
    assert issues(ctx.engine) == [] and fares(ctx.engine) == [] and gf.calls == []


def test_due_issues_are_published_and_priced(make_ctx):
    gf = live(option(640), option(700, stops=0))
    source = month(
        quote("ORD", "LJU", *TRIP, 600),
        quote("ORD", "LJU", date(2027, 6, 2), date(2027, 6, 22), 300),  # 21 days: too long
        quote("ORD", "LJU", date(2027, 6, 5), None, 200),  # one way
    )
    ctx = make_ctx(month_source=source, live_sources=[gf])
    uid = add_user(ctx.engine)

    counts = stage.run(ctx)

    assert issues(ctx.engine) == [(uid, LIPNICA, RUN)]
    assert (counts["users"], counts["published"], counts["priced_due"]) == (1, 1, 1)
    assert (counts["scans"], counts["checked"], counts["found"]) == (1, 1, 1)
    assert [c[:3] for c in source.calls] == [("ORD", "LJU", JUNE)]
    assert [(q.origin, q.dest_airport, q.depart_date, q.return_date, q.return_from) for q in gf.calls] == [
        ("ORD", "LJU", *TRIP, None)
    ]
    [row] = fares(ctx.engine)
    assert (row.user_id, row.gem_slug, row.run_date, row.status) == (uid, LIPNICA, RUN, "found")
    assert (row.origin, row.airport, row.return_airport) == ("ORD", "LJU", "LJU")
    assert (row.depart_date, row.return_date, row.price, row.currency) == (*TRIP, 640, "USD")
    assert (row.fits, row.fit_month, row.pto_cost) == (True, 6, 5)
    assert row.deep_link == "https://flights.example/x"

    again = stage.run(ctx)  # the same day: nothing new to publish or price
    assert (again["published"], again["priced_due"], again["checked"]) == (0, 0, 0)
    assert len(fares(ctx.engine)) == 1 and len(gf.calls) == 1


def test_no_open_ranges_prices_the_best_months(make_ctx):
    september = date(2027, 9, 1)
    source = month(quote("ORD", "LJU", date(2027, 9, 4), date(2027, 9, 12), 500), when=september)
    ctx = make_ctx(month_source=source, live_sources=[live(option(520))])
    add_user(ctx.engine, windows=())

    assert stage.run(ctx)["found"] == 1

    assert [c[2] for c in source.calls] == [date(2027, 5, 1), JUNE, september]
    [row] = fares(ctx.engine)
    assert (row.status, row.price, row.fits, row.fit_month) == ("found", 520, False, None)
    assert row.pto_cost is not None


def test_a_trip_too_costly_for_the_pto_left_does_not_fit(make_ctx):
    ctx = make_ctx(month_source=month(quote("ORD", "LJU", *TRIP, 600)), live_sources=[live(option(640))])
    add_user(ctx.engine, pto_days_total=3)

    stage.run(ctx)

    [row] = fares(ctx.engine)
    assert (row.status, row.fits, row.pto_cost) == ("found", False, 5)


def test_no_cached_candidate_stores_none(make_ctx):
    gf = live(option(500))
    ctx = make_ctx(month_source=month(), live_sources=[gf])
    uid = add_user(ctx.engine)

    counts = stage.run(ctx)

    assert (counts["none"], counts["checked"]) == (1, 0) and gf.calls == []
    [row] = fares(ctx.engine)
    assert (row.user_id, row.gem_slug, row.status, row.price) == (uid, LIPNICA, "none", None)
    assert (row.origin, row.airport, row.depart_date, row.fits) == ("ORD", "LJU", None, None)


def test_a_failed_live_check_is_stored_as_failed(make_ctx):
    ctx = make_ctx(
        month_source=month(quote("ORD", "LJU", *TRIP, 600)),
        live_sources=[FakeLiveSource("google_flights", failing())],
    )
    add_user(ctx.engine)

    assert stage.run(ctx)["failed"] == 1

    [row] = fares(ctx.engine)
    assert (row.status, row.price, row.depart_date) == ("failed", None, TRIP[0])


def test_live_checks_are_capped_and_rerun_safe(make_ctx):
    assert config.GEM_LIVE_CHECKS_PER_DAY == 8
    slept = []
    gf = live(option(500))
    ctx = make_ctx(month_source=month(quote("ORD", "LJU", *TRIP, 400)), live_sources=[gf], sleep=slept.append)
    for n in range(10):
        add_user(ctx.engine, email=f"user{n}@example.com")

    counts = stage.run(ctx)

    assert (counts["published"], counts["checked"], counts["held_live_cap"]) == (10, 8, 2)
    assert len(slept) == 7 and all(config.LIVE_DELAY_S[0] <= s <= config.LIVE_DELAY_S[1] for s in slept)
    again = stage.run(ctx)  # a re-run gets no fresh allowance
    assert (again["checked"], again["held_live_cap"]) == (0, 2)
    assert len(fares(ctx.engine)) == 8 and len(gf.calls) == 8

    ctx.run_date = RUN + timedelta(days=1)  # tomorrow: the two waiting are checked first
    assert stage.run(ctx)["checked"] == 2


def test_recheck_waits_three_days(make_ctx):
    assert config.GEM_RECHECK_DAYS == 3
    gf = live(option(500))
    ctx = make_ctx(month_source=month(quote("ORD", "LJU", *TRIP, 400)), live_sources=[gf])
    add_user(ctx.engine)
    stage.run(ctx)

    for days in (1, 2):
        ctx.run_date = RUN + timedelta(days=days)
        assert stage.run(ctx)["priced_due"] == 0
    ctx.run_date = RUN + timedelta(days=3)
    assert stage.run(ctx)["checked"] == 1

    assert [r.run_date for r in fares(ctx.engine)] == [RUN, RUN + timedelta(days=3)]


def test_only_the_newest_issues_are_priced_and_retired_gems_never(make_ctx, tmp_path, monkeypatch):
    for path in FIXTURES.glob("*.yaml"):
        (tmp_path / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    hoegvik = tmp_path / "hoegvik-islands.yaml"
    hoegvik.write_text(
        hoegvik.read_text(encoding="utf-8").replace("status: approved", "status: retired"), encoding="utf-8"
    )
    monkeypatch.setenv(gems.GEMS_DIR_ENV, str(tmp_path))
    source = FakeMonthSource()
    ctx = make_ctx(month_source=source, live_sources=[live(option(500))])
    uid = add_user(ctx.engine)
    with session_scope(ctx.engine) as s:
        s.add(GemIssue(user_id=uid, gem_slug="hoegvik-islands", published_on=RUN - timedelta(days=3)))

    counts = stage.run(ctx)

    assert (counts["published"], counts["priced_due"]) == (0, 0)  # not a week yet; the one issue retired
    assert source.calls == []


def test_open_jaw_gems_fly_home_from_their_return_airport(make_ctx):
    jaw = live(option(700), open_jaw=True)
    ctx = make_ctx(month_source=month(quote("ORD", "BOO", *TRIP, 600), airport="BOO"), live_sources=[jaw])
    add_user(ctx.engine, trip_styles=["islands"])

    stage.run(ctx)

    [q] = jaw.calls
    assert (q.dest_airport, q.return_from) == ("BOO", "SVJ")
    [row] = fares(ctx.engine)
    assert (row.airport, row.return_airport, row.status) == ("BOO", "SVJ", "found")


def test_open_jaw_gems_fall_back_to_a_round_trip_where_the_source_cannot(make_ctx):
    gf = live(option(700))  # google_flights can't price open jaw
    ctx = make_ctx(month_source=month(quote("ORD", "BOO", *TRIP, 600), airport="BOO"), live_sources=[gf])
    add_user(ctx.engine, trip_styles=["islands"])

    stage.run(ctx)

    [q] = gf.calls
    assert (q.dest_airport, q.return_from) == ("BOO", None)
    [row] = fares(ctx.engine)
    assert (row.airport, row.return_airport, row.status) == ("BOO", "BOO", "found")


def test_serpapi_is_never_used(make_ctx):
    serp = FakeLiveSource("serpapi", answering(option(500), source="serpapi"), supports_open_jaw=True)
    ctx = make_ctx(month_source=month(quote("ORD", "LJU", *TRIP, 400)), live_sources=[serp])
    add_user(ctx.engine)

    counts = stage.run(ctx)

    assert counts["checked"] == 0 and serp.calls == [] and fares(ctx.engine) == []
    gf = live(option(500))
    ctx.live_sources = [serp, gf]
    assert stage.run(ctx)["found"] == 1
    assert serp.calls == [] and len(gf.calls) == 1


def test_a_miserable_only_result_is_none(make_ctx):
    awful = replace(option(500), longest_layover_min=600, longest_layover_airport="JFK")
    ctx = make_ctx(
        month_source=month(quote("ORD", "LJU", *TRIP, 400)),
        live_sources=[live(awful, option(450, stops=3))],  # the other breaks the stop filter
    )
    add_user(ctx.engine)

    counts = stage.run(ctx)

    assert (counts["checked"], counts["none"], counts["found"]) == (1, 1, 0)
    [row] = fares(ctx.engine)
    assert (row.status, row.price, row.depart_date) == ("none", None, TRIP[0])


def test_dry_run_checks_nothing(make_ctx):
    gf = live(option(500))
    ctx = make_ctx(month_source=month(quote("ORD", "LJU", *TRIP, 400)), live_sources=[gf], dry_run=True)
    add_user(ctx.engine)
    add_user(ctx.engine, email="other@example.com", home_airport="MDW")  # no candidate: no row either

    counts = stage.run(ctx)

    assert (counts["would_check"], counts["checked"]) == (1, 0)
    assert gf.calls == [] and fares(ctx.engine) == []
    ctx.dry_run = False
    assert stage.run(ctx)["checked"] == 1


def test_without_a_month_source_publishing_still_runs(make_ctx):
    ctx = make_ctx(live_sources=[live(option(500))])
    add_user(ctx.engine)

    counts = stage.run(ctx)

    assert (counts["published"], counts["priced_due"], counts["scans"]) == (1, 0, 0)
    assert fares(ctx.engine) == []


def test_issued_gems_get_photos(make_ctx, tmp_path, monkeypatch):
    uid = add_user(make_ctx().engine)
    ctx = make_ctx(http=wikimedia({"Lipnica Valley"}))
    with session_scope(ctx.engine) as s:
        for slug in (LIPNICA, "hoegvik-islands"):
            s.add(GemIssue(user_id=uid, gem_slug=slug, published_on=RUN))
        assert photos._due(s, ctx) == ["gem-lipnica-valley"]  # Høgvik's own photo wins

    assert photos.run(ctx)["found"] == 1
    with session_scope(ctx.engine) as s:
        from ptopilot.db.models import PlacePhotoRow

        assert s.get(PlacePhotoRow, "gem-lipnica-valley").status == "ok"

    (tmp_path / "lipnica-valley.yaml").write_text(
        (FIXTURES / "lipnica-valley.yaml").read_text(encoding="utf-8").replace("approved", "retired", 1),
        encoding="utf-8",
    )
    monkeypatch.setenv(gems.GEMS_DIR_ENV, str(tmp_path))
    with session_scope(ctx.engine) as s:
        s.query(PlacePhotoRow).delete()
        assert photos._due(s, ctx) == []  # a retired gem gets no lookup


def test_health_report_has_a_gems_line(make_ctx):
    from ptopilot.pipeline.health import build_report

    ctx = make_ctx(month_source=month(quote("ORD", "LJU", *TRIP, 400)), live_sources=[live(option(500))])
    add_user(ctx.engine)
    counts = stage.run(ctx)

    _, text = build_report(ctx, [runner.StageResult("gems", "ok", counts)])

    assert "Hidden gems: published 1, priced 1, found 1" in text


def test_gems_runs_after_related_and_before_photos():
    names = list(runner.STAGES)
    assert names.index("related") < names.index("gems") < names.index("photos")
    assert "gems" in runner.CONTINUE_ON_FAILURE
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "scan.yml").read_text()
    assert "related, gems, photos" in workflow
