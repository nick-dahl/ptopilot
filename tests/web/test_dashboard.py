"""The signed-in dashboard: PTO bar and one card per destination."""

from sqlalchemy import select

from ptopilot.db.models import PlanningYear, Tracker
from ptopilot.db.session import session_scope
from tests.digest.conftest import add_baseline, add_candidate
from tests.web.conftest import PROFILE_FORM, TODAY, seed_profile, sign_in

TWO_DESTINATIONS = {**PROFILE_FORM, "tracker_dest_1": "MADEIRA", "tracker_min_1": "6", "tracker_max_1": "9"}


def setup(client, emailer, engine, form=TWO_DESTINATIONS) -> dict[str, int]:
    sign_in(client, emailer, engine)
    seed_profile(engine, form)
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


def test_dashboard_pto_bar_uses_the_current_planning_year(client, emailer, clean_engine):
    setup(client, emailer, clean_engine, PROFILE_FORM)
    with session_scope(clean_engine) as s:
        row = s.scalar(select(PlanningYear).where(PlanningYear.year == TODAY.year))
        row.pto_days, row.other_time_off = 30, 4
    page = client.get("/").text
    assert "26</b> PTO days left" in page and "4 of 30 committed" in page
    with session_scope(clean_engine) as s:
        s.delete(s.scalar(select(PlanningYear)))  # no year: fall back to the user's own fields
    assert "15</b> PTO days left" in client.get("/").text


def test_dashboard_card_says_building_price_history(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine, PROFILE_FORM)
    add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY)
    assert "Building price history" in client.get("/").text
    add_baseline(clean_engine, 700)
    assert "Building price history" not in client.get("/").text


def test_dashboard_card_eyebrow_shows_the_target_days(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine, PROFILE_FORM)
    with session_scope(clean_engine) as s:  # a YAML load now gives new trackers a target; clear it
        s.get(Tracker, ids["AZORES"]).target_days = None
    assert "7–10 days on the ground" in client.get("/").text
    with session_scope(clean_engine) as s:
        s.get(Tracker, ids["AZORES"]).target_days = 9
    page = client.get("/").text
    assert "~9 days away" in page and "days on the ground" not in page


def test_empty_dashboard_points_to_destinations_and_plan(client, emailer, clean_engine):
    ids = setup(client, emailer, clean_engine, PROFILE_FORM)
    with session_scope(clean_engine) as s:
        s.get(Tracker, ids["AZORES"]).active = False
    page = client.get("/").text
    assert '<a href="/destinations">' in page and '<a href="/plan">' in page


def test_dashboard_card_shows_fit_notes_and_bookings(client, emailer, clean_engine):
    from ptopilot.db.models import User
    from tests.digest.conftest import book

    ids = setup(client, emailer, clean_engine)
    with session_scope(clean_engine) as s:
        uid = s.scalar(select(User.id))
    book(clean_engine, uid, ids["MADEIRA"], TODAY.replace(day=10), TODAY.replace(day=12), pto_cost=13)
    add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY)
    page = client.get("/").text
    assert "Overlaps your booked Madeira trip." in page
    assert "remaining PTO (2 left)." in page
    assert "Booked Mar 10–12" in page
