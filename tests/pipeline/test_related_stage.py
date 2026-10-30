"""Stage `related`: a light daily watch of the related places users accepted (fake sources; no network).

The seeded user (ORD, open in June 2027, 15 PTO days) tracks the Azores (PDL) aiming at 8 days away and
accepted Madeira (FNC), whose June is "good". June week trips to the Azores typically cost $1000.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from ptopilot import config
from ptopilot.db.models import Destination, PlannedTrip, RelatedCheck, RelatedLink, RouteBaseline, Tracker
from ptopilot.db.session import session_scope
from ptopilot.pipeline import related, runner
from ptopilot.pipeline.context import StageSkipped
from tests.pipeline.conftest import (
    RUN,
    FakeLiveSource,
    FakeMonthSource,
    add_tracker,
    add_user,
    answering,
    failing,
    option,
    quote,
)

JUNE = date(2027, 6, 1)
TRIP = (date(2027, 6, 5), date(2027, 6, 12))  # 8 days away, 5 workdays


def add_link(engine, user_id, tracker_id, airport="FNC", place="MADEIRA") -> int:
    with session_scope(engine) as s:
        link = RelatedLink(
            user_id=user_id, tracker_id=tracker_id, airport=airport, place_code=place, status="accepted"
        )
        s.add(link)
        s.flush()
        return link.id


def add_baseline(engine, dest="PDL", median=1000, confidence="normal", month=JUNE, bucket="week"):
    with session_scope(engine) as s:
        s.add(
            RouteBaseline(
                origin="ORD",
                dest_airport=dest,
                return_airport=dest,
                month=month,
                length_bucket=bucket,
                median=Decimal(median),
                sigma=Decimal(100),
                n=30,
                confidence=confidence,
            )
        )


def setup(engine, main="AZORES", main_airport="PDL", typical=1000) -> tuple[int, int, int]:
    uid = add_user(engine)
    tid = add_tracker(engine, uid, main, target_days=8)
    add_baseline(engine, main_airport, typical)
    return uid, tid, add_link(engine, uid, tid)


def month(*quotes, airport="FNC"):
    return FakeMonthSource({("ORD", airport, JUNE): list(quotes)})


def live(*options):
    return FakeLiveSource("google_flights", answering(*options))


def checks(engine) -> list[RelatedCheck]:
    with session_scope(engine) as s:
        rows = list(s.scalars(select(RelatedCheck).order_by(RelatedCheck.id)))
        s.expunge_all()
        return rows


def test_a_stunning_fitting_fare_is_confirmed(make_ctx):
    gf = live(option(640), option(700, stops=0))
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 600)), live_sources=[gf])
    uid, tid, link_id = setup(ctx.engine)

    counts = related.run(ctx)

    assert counts["links_watched"] == 1 and counts["scans"] == 1 and counts["quotes"] == 1
    assert (counts["promising"], counts["checked"], counts["confirmed"]) == (1, 1, 1)
    assert [(q.origin, q.dest_airport, q.depart_date, q.return_date) for q in gf.calls] == [
        ("ORD", "FNC", *TRIP)
    ]
    [row] = checks(ctx.engine)
    assert (row.run_date, row.user_id, row.tracker_id, row.link_id) == (RUN, uid, tid, link_id)
    assert (row.origin, row.airport, row.depart_date, row.return_date) == ("ORD", "FNC", *TRIP)
    assert (row.cached_price, row.typical_median, row.live_price) == (600, 1000, 640)
    assert (row.currency, row.pto_cost, row.deep_link) == ("USD", 5, "https://flights.example/x")
    assert row.confirmed is True and row.error is None


def test_scans_cover_every_open_month_and_home_airport(make_ctx):
    ctx = make_ctx(month_source=FakeMonthSource(), live_sources=[live(option(640))])
    uid = add_user(
        ctx.engine,
        windows=((date(2027, 6, 20), date(2027, 7, 10)), (date(2027, 2, 1), date(2027, 2, 20))),
        nearby_airports=["MDW"],
    )
    add_link(ctx.engine, uid, add_tracker(ctx.engine, uid, "AZORES"))

    counts = related.run(ctx)

    called = {(origin, dest, m) for origin, dest, m, *_ in ctx.month_source.calls}
    assert called == {(o, "FNC", m) for o in ("ORD", "MDW") for m in (JUNE, date(2027, 7, 1))}
    assert counts["scans"] == 4  # the February range ended before the run date
    assert ctx.month_source.calls[0][3:] == ("US", config.DEFAULT_CURRENCY)


def test_a_range_already_under_way_scans_only_from_the_run_month(make_ctx):
    ctx = make_ctx(month_source=FakeMonthSource(), live_sources=[live(option(640))])
    uid = add_user(ctx.engine, windows=((date(2027, 1, 1), date(2027, 4, 30)),))
    add_link(ctx.engine, uid, add_tracker(ctx.engine, uid, "AZORES"))

    counts = related.run(ctx)

    assert sorted(m for *_, m, _, _ in ctx.month_source.calls) == [date(2027, 3, 1), date(2027, 4, 1)]
    assert counts["scans"] == 2  # not January or February, which are behind the run date


def test_scans_are_shared_across_users(make_ctx):
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 600)), live_sources=[live(option(640))])
    uid, _, _ = setup(ctx.engine)
    other = add_user(ctx.engine, email="ana@example.com")
    add_link(ctx.engine, other, add_tracker(ctx.engine, other, "AZORES", target_days=8))

    counts = related.run(ctx)

    assert counts["scans"] == 1 and len(ctx.month_source.calls) == 1
    assert counts["promising"] == 2 and {r.user_id for r in checks(ctx.engine)} == {uid, other}


def test_a_live_price_that_is_not_stunning_is_not_confirmed(make_ctx):
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 600)), live_sources=[live(option(800))])
    setup(ctx.engine)

    counts = related.run(ctx)

    assert (counts["checked"], counts["confirmed"]) == (1, 0)
    [row] = checks(ctx.engine)
    assert (row.live_price, row.confirmed, row.error) == (800, False, None)


def test_a_failed_live_check_is_stored_and_counts_toward_the_day(make_ctx):
    gf = FakeLiveSource("google_flights", failing("blocked by consent page"))
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 600)), live_sources=[gf])
    setup(ctx.engine)

    counts = related.run(ctx)

    assert (counts["checked"], counts["confirmed"]) == (1, 0)
    [row] = checks(ctx.engine)
    assert row.confirmed is False and row.live_price is None and "blocked" in row.error


def test_no_normal_baseline_skips_the_pair(make_ctx):
    gf = live(option(400))
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 400)), live_sources=[gf])
    uid = add_user(ctx.engine)
    tid = add_tracker(ctx.engine, uid, "AZORES", target_days=8)
    add_link(ctx.engine, uid, tid)
    add_baseline(ctx.engine, "PDL", 1000, confidence="low")

    counts = related.run(ctx)

    assert counts["skipped_no_typical"] == 1 and counts["promising"] == 0
    assert gf.calls == [] and checks(ctx.engine) == []


def test_no_seasons_means_never_surfaced(make_ctx):
    """An added place whose climate lookup failed has no ratings: fail closed, unlike SeasonTable.rating."""
    gf = live(option(400))
    ctx = make_ctx(month_source=month(quote("ORD", "TFS", *TRIP, 400), airport="TFS"), live_sources=[gf])
    uid = add_user(ctx.engine)
    tid = add_tracker(ctx.engine, uid, "AZORES", target_days=8)
    add_baseline(ctx.engine)
    with session_scope(ctx.engine) as s:
        s.add(Destination(code="TFS_ES", name="Tenerife", kind="region", airports=["TFS"]))
    add_link(ctx.engine, uid, tid, "TFS", "TFS_ES")

    counts = related.run(ctx)

    assert counts["quotes"] == 1 and counts["promising"] == 0 and gf.calls == []


def test_a_fare_outside_the_season_or_band_does_not_fit(make_ctx):
    ctx = make_ctx(
        month_source=month(
            quote("ORD", "FNC", date(2027, 6, 5), date(2027, 6, 18), 600),  # 14 days: outside 6..10
            quote("ORD", "FNC", date(2027, 6, 5), date(2027, 6, 9), 600),  # 5 days
        ),
        live_sources=[live(option(500))],
    )
    setup(ctx.engine)

    assert related.run(ctx)["promising"] == 0


def test_without_a_target_the_users_trip_lengths_apply(make_ctx):
    ctx = make_ctx(
        month_source=month(quote("ORD", "FNC", date(2027, 6, 5), date(2027, 6, 18), 600)),  # 14 days
        live_sources=[live(option(500))],
    )
    uid = add_user(ctx.engine)
    tid = add_tracker(ctx.engine, uid, "AZORES")
    add_baseline(ctx.engine, bucket="long")
    add_link(ctx.engine, uid, tid)

    assert related.run(ctx)["promising"] == 1


def test_a_shared_related_airport_uses_the_strictest_typical(make_ctx):
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 700)), live_sources=[live(option(500))])
    uid, _, _ = setup(ctx.engine, "AZORES", "PDL", 1000)
    lisbon = add_tracker(ctx.engine, uid, "LIS", target_days=8)
    add_baseline(ctx.engine, "LIS", 800)
    lisbon_link = add_link(ctx.engine, uid, lisbon)

    assert related.run(ctx)["promising"] == 0  # 700 is 30% below the Azores, but needs <= 600 for Lisbon

    ctx.month_source.quotes[("ORD", "FNC", JUNE)] = [quote("ORD", "FNC", *TRIP, 590)]
    counts = related.run(ctx)
    assert counts["promising"] == 1
    [row] = checks(ctx.engine)
    assert (row.tracker_id, row.link_id, row.typical_median) == (lisbon, lisbon_link, 800)


def test_the_cheapest_quote_per_trip_is_kept(make_ctx):
    gf = live(option(500))
    ctx = make_ctx(
        month_source=month(quote("ORD", "FNC", *TRIP, 650), quote("ORD", "FNC", *TRIP, 600)),
        live_sources=[gf],
    )
    setup(ctx.engine)

    counts = related.run(ctx)

    assert counts["promising"] == 1 and len(gf.calls) == 1
    assert checks(ctx.engine)[0].cached_price == 600


def trips(n):
    """n distinct fitting June trips, 8 days away, each $10 dearer than the last (from $500)."""
    return [quote("ORD", "FNC", date(2027, 6, 2 + i), date(2027, 6, 9 + i), 500 + 10 * i) for i in range(n)]


def test_live_checks_are_capped_at_five_and_ranked_by_discount(make_ctx):
    quotes = trips(7)
    gf = live(option(500))
    ctx = make_ctx(month_source=month(*reversed(quotes)), live_sources=[gf])
    setup(ctx.engine)

    counts = related.run(ctx)

    assert (counts["promising"], counts["checked"], counts["held_live_cap"]) == (7, 5, 2)
    assert [q.depart_date for q in gf.calls] == [q.depart_date for q in quotes[:5]]
    assert len(checks(ctx.engine)) == config.RELATED_LIVE_CHECKS_PER_DAY == 5


def test_a_rerun_respects_the_daily_live_checks(make_ctx):
    gf = live(option(500))
    ctx = make_ctx(month_source=month(*trips(3)), live_sources=[gf])
    setup(ctx.engine)
    related.run(ctx)
    assert len(gf.calls) == 3

    again = related.run(ctx)  # the same trips were checked today: not again
    assert again["checked"] == 0 and len(gf.calls) == 3

    ctx.month_source.quotes[("ORD", "FNC", JUNE)] = trips(7)
    third = related.run(ctx)  # 3 of today's 5 are used: 2 more
    assert (third["checked"], third["held_live_cap"]) == (2, 2)
    assert len(checks(ctx.engine)) == 5
    assert related.run(ctx)["checked"] == 0


def test_one_way_quotes_are_ignored(make_ctx):
    gf = live(option(300))
    one_way = quote("ORD", "FNC", TRIP[0], None, 300)
    ctx = make_ctx(month_source=month(one_way), live_sources=[gf])
    setup(ctx.engine)

    counts = related.run(ctx)

    assert counts["quotes"] == 1 and counts["promising"] == 0 and gf.calls == []


def test_fares_departing_today_or_earlier_are_ignored(make_ctx):
    ctx = make_ctx(
        run_date=date(2027, 6, 5),
        month_source=month(quote("ORD", "FNC", *TRIP, 500)),
        live_sources=[live(option(500))],
    )
    setup(ctx.engine)

    assert related.run(ctx)["promising"] == 0


def test_serpapi_is_never_used(make_ctx):
    serp = FakeLiveSource("serpapi", answering(option(500), source="serpapi"))
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 600)), live_sources=[serp])
    setup(ctx.engine)

    counts = related.run(ctx)

    assert counts["promising"] == 1 and counts["checked"] == 0 and serp.calls == []
    assert checks(ctx.engine) == []

    gf = live(option(640))
    ctx.live_sources = [serp, gf]
    assert related.run(ctx)["confirmed"] == 1
    assert serp.calls == [] and len(gf.calls) == 1


def test_inactive_or_booked_main_destinations_are_not_watched(make_ctx):
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 600)), live_sources=[live(option(500))])
    uid, tid, _ = setup(ctx.engine)
    with session_scope(ctx.engine) as s:
        s.get(Tracker, tid).active = False
    counts = related.run(ctx)
    assert counts["links_watched"] == 0 and counts["scans"] == 0

    with session_scope(ctx.engine) as s:
        s.get(Tracker, tid).active = True
        trip = s.scalars(select(PlannedTrip).where(PlannedTrip.tracker_id == tid)).one()
        trip.booked_depart, trip.booked_return, trip.booked_pto = date(2027, 9, 1), date(2027, 9, 8), 5
    counts = related.run(ctx)
    assert counts["links_watched"] == 1 and counts["promising"] == 0
    assert checks(ctx.engine) == []


def test_a_fare_overlapping_a_booked_trip_does_not_fit(make_ctx):
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 600)), live_sources=[live(option(500))])
    uid, _, _ = setup(ctx.engine)
    other = add_tracker(ctx.engine, uid, "LIS")
    with session_scope(ctx.engine) as s:
        trip = s.scalars(select(PlannedTrip).where(PlannedTrip.tracker_id == other)).one()
        trip.booked_depart, trip.booked_return, trip.booked_pto = date(2027, 6, 10), date(2027, 6, 14), 3

    assert related.run(ctx)["promising"] == 0


def test_a_miserable_live_itinerary_is_not_confirmed(make_ctx):
    awful = replace(option(500), longest_layover_min=600, longest_layover_airport="JFK")
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 600)), live_sources=[live(awful)])
    setup(ctx.engine)

    counts = related.run(ctx)

    assert (counts["checked"], counts["confirmed"]) == (1, 0)
    [row] = checks(ctx.engine)
    assert row.confirmed is False and row.error is None


def test_options_outside_the_users_filters_are_not_confirmed(make_ctx):
    ctx = make_ctx(
        month_source=month(quote("ORD", "FNC", *TRIP, 600)),
        live_sources=[live(option(500, stops=3), option(520, overnight=True), option(900))],
    )
    setup(ctx.engine)

    related.run(ctx)

    [row] = checks(ctx.engine)
    assert (row.live_price, row.confirmed) == (900, False)


def test_without_a_month_source_the_stage_is_skipped(make_ctx):
    with pytest.raises(StageSkipped):
        related.run(make_ctx())


def test_related_runs_between_score_and_alerts():
    names = list(runner.STAGES)
    assert names.index("score") < names.index("related") < names.index("alerts")
    assert "related" in runner.CONTINUE_ON_FAILURE


def test_health_report_has_a_related_line(make_ctx):
    from ptopilot.pipeline.health import build_report

    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 600)), live_sources=[live(option(640))])
    setup(ctx.engine)
    counts = related.run(ctx)

    _, text = build_report(ctx, [runner.StageResult("related", "ok", counts)])

    assert "Related places: promising 1, checked 1, confirmed 1" in text
    with session_scope(ctx.engine) as s:
        assert s.scalar(select(func.count()).select_from(RelatedCheck)) == 1


def test_a_dry_run_makes_no_checks_and_leaves_the_days_allowance(make_ctx):
    gf = live(option(500))
    ctx = make_ctx(month_source=month(*trips(7)), live_sources=[gf], dry_run=True)
    setup(ctx.engine)

    counts = related.run(ctx)

    assert (counts["promising"], counts["would_check"], counts["checked"]) == (7, 5, 0)
    assert counts["held_live_cap"] == 2 and gf.calls == [] and checks(ctx.engine) == []

    ctx.dry_run = False
    real = related.run(ctx)  # the real run still has all five checks
    assert (real["checked"], real["would_check"]) == (5, 0) and len(gf.calls) == 5


def test_live_checks_are_paced_but_not_before_the_first(make_ctx):
    slept = []
    ctx = make_ctx(month_source=month(*trips(3)), live_sources=[live(option(500))], sleep=slept.append)
    setup(ctx.engine)

    assert related.run(ctx)["checked"] == 3

    assert len(slept) == 2
    assert all(config.LIVE_DELAY_S[0] <= s <= config.LIVE_DELAY_S[1] for s in slept)


def test_a_place_the_user_now_tracks_is_no_longer_watched_as_related(make_ctx):
    ctx = make_ctx(month_source=month(quote("ORD", "FNC", *TRIP, 600)), live_sources=[live(option(500))])
    uid, _, _ = setup(ctx.engine)
    add_tracker(ctx.engine, uid, "MADEIRA")  # FNC is Madeira's own airport

    counts = related.run(ctx)

    assert counts["links_watched"] == 0 and counts["scans"] == 0
