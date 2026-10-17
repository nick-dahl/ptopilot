from datetime import date, timedelta
from decimal import Decimal

from ptopilot import config
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import DigestSend
from ptopilot.db.session import session_scope
from ptopilot.digest.select import build_digests
from tests.digest.conftest import RUN, add_baseline, add_candidate, add_tracker, add_user

GEO, SEASONS = load_geo(), load_seasons()


def digests(engine, today=RUN, min_level="good"):
    return build_digests(engine, GEO, SEASONS, today, min_level)


def test_nothing_scanned_means_no_digests(clean_engine):
    assert digests(clean_engine) == []


def test_only_deals_by_default_and_everything_with_min_level_none(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 600, level="great")
    add_candidate(clean_engine, t, 650, depart=date(2027, 3, 12), ret=date(2027, 3, 21), level="none")
    [d] = digests(clean_engine)
    assert [c.price for c in d.deals] == [600]
    [d] = digests(clean_engine, min_level="none")
    assert sorted(c.price for c in d.deals) == [600, 650]


def test_uses_the_latest_scan_on_or_before_today(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 700, run_date=RUN - timedelta(days=3))
    add_candidate(clean_engine, t, 600, run_date=RUN)
    assert [c.price for c in digests(clean_engine)[0].deals] == [600]
    assert [c.price for c in digests(clean_engine, today=RUN - timedelta(days=1))[0].deals] == [700]


def test_card_details_typical_price_and_open_jaw(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine), code="CAMINO_PORTUGUES")
    add_candidate(
        clean_engine,
        t,
        900,
        dest="OPO",
        return_airport="SCQ",
        ret=date(2027, 3, 20),
        days_off=("Company day off",),
    )
    add_baseline(clean_engine, 1200, dest="OPO", return_airport="SCQ", bucket="long")
    card = digests(clean_engine)[0].deals[0]
    assert card.destination.startswith("Camino Portugués")
    assert card.open_jaw and (card.dest_airport, card.return_airport) == ("OPO", "SCQ")
    assert (card.typical, card.pct_below) == (Decimal(1200), 25)
    assert card.days_off == ("Company day off",)
    assert (card.carrier, card.stops, card.flight_numbers) == ("Tap Air Portugal", 1, ("TP 202",))
    assert card.weather_note  # March note for the Camino


def test_snoozed_tracker_sends_no_deals_but_stays_in_the_overview(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine), snoozed_until=RUN + timedelta(days=10))
    add_candidate(clean_engine, t, 600)
    [d] = digests(clean_engine)
    assert d.quiet
    assert [(r.destination, r.snoozed_until) for r in d.trackers] == [("Azores", RUN + timedelta(days=10))]


def test_already_sent_deal_is_resent_only_when_meaningfully_cheaper(clean_engine):
    uid = add_user(clean_engine)
    t = add_tracker(clean_engine, uid)
    old = add_candidate(clean_engine, t, 600, run_date=RUN - timedelta(days=3))
    with session_scope(clean_engine) as s:
        s.add(DigestSend(user_id=uid, items=[{"candidate_id": old, "price": 600.0}]))
    add_candidate(clean_engine, t, 590, run_date=RUN)  # only 1.7% cheaper than what was sent
    assert digests(clean_engine)[0].deals == []
    add_candidate(
        clean_engine, t, 560, depart=date(2027, 3, 5), run_date=RUN + timedelta(days=1), evening=True
    )
    assert [c.price for c in digests(clean_engine, today=RUN + timedelta(days=1))[0].deals] == [560]


def test_per_tracker_and_total_caps_keep_every_trackers_best(clean_engine, monkeypatch):
    monkeypatch.setattr(config, "DIGEST_MAX_DEALS", 4)
    uid = add_user(clean_engine)
    azores, madeira = add_tracker(clean_engine, uid), add_tracker(clean_engine, uid, code="MADEIRA")
    for i in range(5):
        week = timedelta(days=7 * (i % 3))
        add_candidate(
            clean_engine,
            azores,
            600 + i,
            depart=date(2027, 3, 5) + week,
            ret=date(2027, 3, 14) + week,
            evening=i < 3,
            go_now=90 - i,
        )
    add_candidate(clean_engine, madeira, 800, dest="FNC", go_now=50)
    deals = digests(clean_engine)[0].deals
    assert len(deals) == 4
    assert sum(1 for d in deals if d.tracker_id == azores) == 3  # best + 2 alternates
    assert any(d.tracker_id == madeira for d in deals)  # Madeira's best beats Azores' alternates for a slot


def test_tracker_overview_trend_and_next_good_month(clean_engine):
    uid = add_user(clean_engine)
    t = add_tracker(clean_engine, uid)
    add_tracker(clean_engine, uid, code="MADEIRA")
    add_candidate(clean_engine, t, 700, run_date=RUN - timedelta(days=7))
    add_candidate(clean_engine, t, 600, run_date=RUN)
    rows = {r.destination: r for r in digests(clean_engine)[0].trackers}
    assert (rows["Azores"].best_price, rows["Azores"].trend) == (600, "down")
    assert rows["Azores"].next_good_month == "May"
    assert (rows["Madeira"].best_price, rows["Madeira"].trend, rows["Madeira"].next_good_month) == (
        None,
        "new",
        "Mar",
    )


def test_users_without_active_trackers_get_no_digest(clean_engine):
    add_user(clean_engine, "idle@example.com")
    t = add_tracker(clean_engine, add_user(clean_engine, "off@example.com"), active=False)
    add_candidate(clean_engine, t, 600)
    assert digests(clean_engine) == []
