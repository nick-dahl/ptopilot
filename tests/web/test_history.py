"""Queries behind the dashboard cards and the destination page."""

from datetime import date, timedelta
from decimal import Decimal

from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Candidate, Tracker
from ptopilot.db.session import session_scope
from ptopilot.web.history import destination_summaries, trend, trip_options, typical_band
from tests.digest.conftest import RUN, add_baseline, add_candidate, add_tracker, add_user

GEO, SEASONS = load_geo(), load_seasons()


def options(engine, tracker_id, today=RUN):
    return trip_options(engine, GEO, SEASONS, tracker_id, today)


def test_trip_options_are_the_latest_scan_cheapest_first(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 700, depart=date(2027, 3, 12), ret=date(2027, 3, 21))
    add_candidate(clean_engine, t, 603)
    add_candidate(clean_engine, t, 999, run_date=RUN - timedelta(days=1), depart=date(2027, 3, 19))
    got = options(clean_engine, t)
    assert [o.price for o in got] == [603, 700]
    first = got[0]
    assert (first.depart_date, first.return_date, first.pto_cost, first.days_away) == (
        date(2027, 3, 5), date(2027, 3, 14), 5, 10,
    )  # fmt: skip
    assert (first.carrier, first.stops) == ("Tap Air Portugal", 1)
    assert first.deep_link.startswith("https://www.google.com/travel/flights")


def test_trip_options_ignore_scans_after_today(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 650)
    add_candidate(clean_engine, t, 500, run_date=RUN + timedelta(days=1))
    assert [o.price for o in options(clean_engine, t)] == [650]


def test_trip_options_carry_bar_geometry_when_a_baseline_exists(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 603)
    add_candidate(clean_engine, t, 700, dest="FNC")
    add_baseline(clean_engine, 700)  # JFK-PDL only, sigma 50
    by_dest = {o.dest_airport: o for o in options(clean_engine, t)}
    assert by_dest["PDL"].bar is not None and by_dest["PDL"].bar.dot < by_dest["PDL"].bar.band_start
    assert by_dest["PDL"].pct_below == 14
    assert by_dest["FNC"].bar is None and by_dest["FNC"].pct_below is None


def test_snoozed_and_excluded_trips_are_kept_but_dimmed(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    keep = add_candidate(clean_engine, t, 603)
    hidden = add_candidate(clean_engine, t, 650, depart=date(2027, 3, 12), ret=date(2027, 3, 21))
    with session_scope(clean_engine) as s:
        s.get(Candidate, hidden).state = "excluded"
    dimmed = {o.candidate_id: o.dimmed for o in options(clean_engine, t)}
    assert dimmed == {keep: False, hidden: True}


def test_open_jaw_options_know_where_they_fly_home_from(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine), code="CAMINO_PORTUGUES")
    add_candidate(clean_engine, t, 852, dest="OPO", return_airport="SCQ")
    (o,) = options(clean_engine, t)
    assert o.open_jaw and (o.dest_airport, o.return_airport) == ("OPO", "SCQ")


def test_trend_is_the_cheapest_price_per_scan_day(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    for days_ago, prices in [(2, (720, 700)), (1, (690,)), (0, (650, 680))]:
        for i, price in enumerate(prices):
            add_candidate(
                clean_engine, t, price, run_date=RUN - timedelta(days=days_ago), depart=date(2027, 3, 5 + i)
            )
    assert [(p.run_date, p.price) for p in trend(clean_engine, t, RUN)] == [
        (RUN - timedelta(days=2), Decimal(700)),
        (RUN - timedelta(days=1), Decimal(690)),
        (RUN, Decimal(650)),
    ]


def test_trend_covers_only_the_last_30_days_and_this_tracker(clean_engine):
    user = add_user(clean_engine)
    t, other = add_tracker(clean_engine, user), add_tracker(clean_engine, user, code="MADEIRA")
    add_candidate(clean_engine, t, 650)
    add_candidate(clean_engine, t, 600, run_date=RUN - timedelta(days=30))  # just outside the window
    add_candidate(clean_engine, other, 500, dest="FNC")
    assert [p.price for p in trend(clean_engine, t, RUN)] == [Decimal(650)]
    assert trend(clean_engine, t, RUN - timedelta(days=60)) == []


def test_typical_band_comes_from_the_cheapest_trips_baseline(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 603)
    add_baseline(clean_engine, 700)
    assert typical_band(options(clean_engine, t)) == (Decimal(650), Decimal(750))
    assert typical_band([]) is None


def test_summaries_list_priced_destinations_cheapest_first_then_the_rest(clean_engine):
    user = add_user(clean_engine)
    azores = add_tracker(clean_engine, user)
    madeira = add_tracker(clean_engine, user, code="MADEIRA")
    patagonia = add_tracker(clean_engine, user, code="PATAGONIA")
    add_candidate(clean_engine, azores, 700)
    add_candidate(clean_engine, madeira, 603, dest="FNC")
    got = destination_summaries(clean_engine, GEO, SEASONS, user, RUN)
    assert [(s.tracker_id, s.best.price if s.best else None) for s in got] == [
        (madeira, 603), (azores, 700), (patagonia, None),
    ]  # fmt: skip
    assert got[0].name == "Madeira" and got[0].palette.color == "#15803d"
    assert got[0].stay == (7, 10)


def test_summaries_show_snoozes_and_skip_inactive_trackers(clean_engine):
    user = add_user(clean_engine)
    snoozed = add_tracker(clean_engine, user, snoozed_until=RUN + timedelta(days=10))
    gone = add_tracker(clean_engine, user, code="MADEIRA")
    with session_scope(clean_engine) as s:
        s.get(Tracker, gone).active = False
    (only,) = destination_summaries(clean_engine, GEO, SEASONS, user, RUN)
    assert only.tracker_id == snoozed and only.snoozed_until == RUN + timedelta(days=10)


def test_summaries_ignore_other_users(clean_engine):
    mine = add_user(clean_engine)
    add_tracker(clean_engine, add_user(clean_engine, "other@example.com"))
    assert destination_summaries(clean_engine, GEO, SEASONS, mine, RUN) == []


def test_a_summarys_best_trip_skips_excluded_ones(clean_engine):
    user = add_user(clean_engine)
    t = add_tracker(clean_engine, user)
    excluded = add_candidate(clean_engine, t, 500)
    add_candidate(clean_engine, t, 650, depart=date(2027, 3, 12), ret=date(2027, 3, 21))
    with session_scope(clean_engine) as s:
        s.get(Candidate, excluded).state = "excluded"
    (summary,) = destination_summaries(clean_engine, GEO, SEASONS, user, RUN)
    assert summary.best.price == 650
