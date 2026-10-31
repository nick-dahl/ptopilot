"""The dashboard's hero (the deal that brought you here), its quiet-day line, and the photo cards."""

import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from ptopilot.core.fit import BookedTrip
from ptopilot.core.geo import Palette
from ptopilot.db.models import PipelineRun, Tracker
from ptopilot.db.session import session_scope
from ptopilot.web.history import DestinationSummary, TripOption, hero_deal
from ptopilot.web.viz import TrendPoint, sparkline
from tests.digest.conftest import add_baseline, add_candidate
from tests.web.conftest import PROFILE_FORM, TODAY, seed_profile, sign_in

TWO = {
    **PROFILE_FORM,
    "tracker_dest_1": "MADEIRA",
    "tracker_min_1": "7",
    "tracker_max_1": "10",
}


def trip(
    tracker_id=1, candidate_id=1, price=600, level="good", go_now=60, standout=False, **kw
) -> TripOption:
    return TripOption(
        candidate_id=candidate_id,
        tracker_id=tracker_id,
        origin="JFK",
        dest_airport="PDL",
        return_airport="PDL",
        depart_date=date(2027, 3, 12),
        return_date=date(2027, 3, 21),
        evening_departure=False,
        price=Decimal(price),
        currency="USD",
        pto_cost=5,
        days_away=10,
        season_rating="good",
        weather_note=None,
        carrier=None,
        stops=1,
        overnight=False,
        deep_link=None,
        deal_level=level,
        go_now=go_now,
        state="new",
        median=900.0,
        sigma=50.0,
        bar=None,
        standout=standout,
        **kw,
    )


def summary(tracker_id, best, **kw) -> DestinationSummary:
    return DestinationSummary(
        tracker_id=tracker_id,
        code=f"P{tracker_id}",
        name=f"Place {tracker_id}",
        palette=Palette("#0e7490", "#cffafe"),
        stay=(7, 10),
        best=best,
        **{"snoozed_until": None, "next_good_month": None, "headline": best, **kw},
    )


def test_hero_prefers_a_standout_then_a_great_deal():
    good = summary(1, trip(1, 1, 400, "good", 70))
    great = summary(2, trip(2, 2, 700, "great", 80))
    greater = summary(3, trip(3, 3, 800, "great", 84))
    rare = summary(4, trip(4, 4, 900, "great", 88, standout=True, expected_days=2))
    rarer = summary(5, trip(5, 5, 950, "great", 95, standout=True, expected_days=2))
    assert hero_deal([good, great, greater, rare, rarer]) is rarer
    assert hero_deal([good, great, greater]) is greater
    assert hero_deal([good]) is None
    assert hero_deal([]) is None


def test_snoozed_booked_or_ruled_out_are_never_the_hero():
    rare = trip(1, 1, 900, "great", 95, standout=True, expected_days=2)
    snoozed = summary(1, rare, snoozed_until=TODAY + timedelta(days=30))
    booked = summary(
        2, replace(rare, tracker_id=2), booked=(BookedTrip(2, "Place 2", 2027, TODAY, TODAY, 3, None, None),)
    )
    ruled_out = summary(3, None, ruled_out=True)
    ruled_out = replace(ruled_out, headline=replace(rare, tracker_id=3))
    fallback = summary(4, trip(4, 4, 700, "great", 80))
    assert hero_deal([snoozed, booked, ruled_out]) is None
    assert hero_deal([snoozed, booked, ruled_out, fallback]) is fallback


def setup(client, emailer, engine, form=TWO) -> dict[str, int]:
    sign_in(client, emailer, engine)
    seed_profile(engine, form)
    with session_scope(engine) as s:
        return {t.destination_code: t.id for t in s.scalars(select(Tracker))}


def hero(page: str) -> str | None:
    found = re.search(r'<section id="hero".*?</section>', page, re.S)
    return found.group(0) if found else None


def test_quiet_day_has_no_hero(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY, level="good", go_now=60)
    add_candidate(clean_engine, ids["MADEIRA"], 650, run_date=TODAY, level="none", go_now=10, dest="FNC")
    with session_scope(clean_engine) as s:
        s.add(
            PipelineRun(
                run_date=TODAY,
                stage="score",
                status="ok",
                finished_at=datetime.combine(TODAY, datetime.min.time(), UTC).replace(hour=6, minute=12),
            )
        )
    page = client.get("/").text
    assert hero(page) is None and "data-candidate-id" not in page
    assert "No standout fares today · checked 2 trips at 06:12" in page
    assert 'class="dest-card' in page  # the photo cards still show


def test_hero_shows_the_countdown_only_within_a_week(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine)
    add_baseline(clean_engine, 900)
    c = add_candidate(
        clean_engine, ids["AZORES"], 603, run_date=TODAY, level="great", go_now=80, expected_days=5
    )
    page = hero(client.get("/").text)
    assert page is not None and "No standout fares today" not in page
    assert "~5 days" in page and "before it's likely gone" in page
    assert "Azores, March 2027" in page and "$603" in page and "33% below typical ($900)" in page
    assert "JFK → " in page and "10 days for 5 PTO · 1 stop" in page
    assert "likely gone within ~5 days" in page  # the pill: the duration label
    assert f'name="candidate_id" value="{c}"' in page and f'action="/trackers/{ids["AZORES"]}/snooze"' in page
    assert "View flights" in page and "I booked this" in page and "data-inplace" in page

    with session_scope(clean_engine) as s:
        from ptopilot.db.models import Candidate

        s.get(Candidate, c).expected_days = 9
    page = hero(client.get("/").text)
    assert page is not None and "before it's likely gone" not in page


def test_standout_hero_carries_the_dialog_hook(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine)
    add_baseline(clean_engine, 900)
    great = add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY, level="great", go_now=80)
    page = client.get("/").text
    assert hero(page) is not None and "Great deal" in hero(page)
    assert "data-candidate-id" not in page and 'role="dialog"' not in page

    rare = add_candidate(
        clean_engine,
        ids["MADEIRA"],
        640,
        run_date=TODAY,
        level="great",
        go_now=95,
        expected_days=2,
        dest="FNC",
    )
    page = client.get("/").text
    assert f'data-candidate-id="{rare}"' in page and f'data-candidate-id="{great}"' not in page
    assert "Rare · likely gone within ~2 days" in hero(page)
    assert 'role="dialog"' in page and 'aria-modal="true"' in page and 'aria-label="Close"' in page
    assert '<script type="module" src="/static/hero.js"></script>' in page


def test_cards_link_to_the_destination_page(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY, level="good", go_now=60)
    for days_ago, price in ((3, 700), (2, 680), (1, 650)):
        add_candidate(
            clean_engine, ids["AZORES"], price, run_date=TODAY - timedelta(days=days_ago), level="good"
        )
    with session_scope(clean_engine) as s:
        s.get(Tracker, ids["MADEIRA"]).snoozed_until = TODAY + timedelta(days=30)
    page = client.get("/").text
    azores = re.search(rf'<a class="dest-card[^"]*"[^>]*href="/trackers/{ids["AZORES"]}".*?</a>', page, re.S)
    assert azores is not None
    card = azores.group(0)
    assert "<h2>Azores</h2>" in card and "$603" in card and "Good deal" in card
    assert "Mar 5–14 · 5 PTO" in card
    assert "Price falling" in card  # the trend arrow has words, not only a glyph
    madeira = re.search(
        rf'<a class="dest-card[^"]*"[^>]*href="/trackers/{ids["MADEIRA"]}".*?</a>', page, re.S
    )
    assert madeira is not None and 'class="badge">Snoozed' in madeira.group(0)


def test_sparkline_needs_enough_points():
    day = date(2027, 3, 1)
    assert sparkline([]) is None
    assert (
        sparkline([TrendPoint(day, Decimal(500)), TrendPoint(day + timedelta(days=1), Decimal(400))]) is None
    )
    points = [TrendPoint(day + timedelta(days=i), Decimal(p)) for i, p in enumerate((500, 400, 450))]
    line = sparkline(points)
    coords = [tuple(map(float, pair.split(","))) for pair in line.split()]
    assert len(coords) == 3
    assert coords[0][0] == 0 and coords[-1][0] == 230
    assert all(0 <= y <= 60 for _, y in coords)
    assert coords[1][1] > coords[0][1]  # the cheapest day sits lowest
