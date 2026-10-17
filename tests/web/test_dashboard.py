"""The signed-in dashboard: PTO bar and one card per destination."""

from sqlalchemy import select

from ptopilot.db.models import Tracker
from ptopilot.db.session import session_scope
from tests.digest.conftest import add_baseline, add_candidate
from tests.web.conftest import PROFILE_FORM, TODAY, sign_in

TWO_DESTINATIONS = {**PROFILE_FORM, "tracker_dest_1": "MADEIRA", "tracker_min_1": "6", "tracker_max_1": "9"}


def setup(client, emailer, engine, form=TWO_DESTINATIONS) -> dict[str, int]:
    sign_in(client, emailer, engine)
    client.post("/profile", data=form)
    with session_scope(engine) as s:
        return {t.destination_code: t.id for t in s.scalars(select(Tracker))}


def test_cards_show_each_destinations_best_trip_cheapest_first(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, ids["AZORES"], 700, run_date=TODAY)
    add_candidate(clean_engine, ids["AZORES"], 650, run_date=TODAY, depart=TODAY.replace(day=12),
                  ret=TODAY.replace(day=21))  # fmt: skip
    add_candidate(clean_engine, ids["MADEIRA"], 603, run_date=TODAY, dest="FNC")
    page = client.get("/").text
    assert page.index("Madeira") < page.index("Azores")
    assert "$603" in page and "$650" in page and "$700" not in page  # best trip per destination only
    assert f'href="/trackers/{ids["AZORES"]}"' in page and "--dest:#0e7490" in page
    assert "Mar 12–21 · 5 PTO for 10 days" in page


def test_card_places_the_price_against_the_typical_range(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine, PROFILE_FORM)
    add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY)
    add_baseline(clean_engine, 700)
    page = client.get("/").text
    assert "14% below typical" in page and 'class="pbar"' in page


def test_dashboard_says_when_prices_were_last_checked(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine, PROFILE_FORM)
    add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY)
    assert "Prices from the Thu Mar 4 scan" in client.get("/").text


def test_pto_bar_shows_days_left_and_committed(client, emailer, clean_engine):
    setup(client, emailer, clean_engine, PROFILE_FORM)
    page = client.get("/").text
    assert "15</b> PTO days left" in page and "7 of 22 committed" in page


def test_no_trackers_points_to_the_profile(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine, PROFILE_FORM)
    with session_scope(clean_engine) as s:
        s.get(Tracker, ids["AZORES"]).active = False
    assert 'No destinations yet. <a href="/profile">' in client.get("/").text
