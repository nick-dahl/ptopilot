"""The destination page: every date option from the latest scan, and the cheapest fare over 30 days."""

from datetime import date, timedelta

from sqlalchemy import select

from ptopilot.db.models import Candidate, Tracker
from ptopilot.db.session import session_scope
from tests.digest.conftest import add_baseline, add_candidate, set_verdict
from tests.web.conftest import PROFILE_FORM, TODAY, seed_profile, sign_in

CAMINO = {**PROFILE_FORM, "tracker_dest_0": "CAMINO_PORTUGUES", "tracker_min_0": "11", "tracker_max_0": "14"}


def setup(client, emailer, engine, form=PROFILE_FORM, email="nick@example.com") -> int:
    sign_in(client, emailer, engine, email)
    seed_profile(engine, form, email)
    with session_scope(engine) as s:
        return s.scalar(select(Tracker.id).order_by(Tracker.id.desc()))


def test_lists_every_trip_from_the_latest_scan_cheapest_first(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    later = {"depart": TODAY.replace(day=12), "ret": TODAY.replace(day=21)}
    add_candidate(clean_engine, t, 700, run_date=TODAY, **later)
    add_candidate(clean_engine, t, 603, run_date=TODAY)
    add_baseline(clean_engine, 700)
    page = client.get(f"/trackers/{t}")
    assert page.status_code == 200
    text = page.text
    assert "<h1>Azores</h1>" in text and "7–10 days on the ground" in text
    assert text.index("$603") < text.index("$700")
    assert "Fri Mar 5 → Sun Mar 14" in text and "Tap Air Portugal · 1 stop" in text
    assert 'href="https://www.google.com/travel/flights/search?tfs=X"' in text and "View flights" in text
    assert "14% below typical" in text


def test_open_jaw_trips_say_where_they_fly_home_from(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine, CAMINO)
    add_candidate(clean_engine, t, 852, run_date=TODAY, dest="OPO", return_airport="SCQ")
    assert "into OPO · home from SCQ" in client.get(f"/trackers/{t}").text


def test_excluded_trips_stay_visible_but_dimmed(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    c = add_candidate(clean_engine, t, 603, run_date=TODAY)
    with session_scope(clean_engine) as s:
        s.get(Candidate, c).state = "excluded"
    assert '<tr class="dimmed">' in client.get(f"/trackers/{t}").text


def test_trend_needs_a_few_scans_before_it_draws(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, t, 603, run_date=TODAY)
    page = client.get(f"/trackers/{t}").text
    assert "Price history fills in after a few daily scans" in page and "<svg" not in page
    for days_ago, price in [(1, 640), (2, 660)]:
        add_candidate(clean_engine, t, price, run_date=TODAY - timedelta(days=days_ago))
    page = client.get(f"/trackers/{t}").text
    assert 'class="trend"' in page and "Cheapest fare, last 30 days" in page
    assert "Tue Mar 2" in page and "Thu Mar 4" in page  # first and last scan days


def test_no_scan_yet_says_so(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    assert "First prices after the next daily scan" in client.get(f"/trackers/{t}").text


def test_snooze_from_the_destination_page(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    assert f'action="/trackers/{t}/snooze"' in client.get(f"/trackers/{t}").text
    client.post(f"/trackers/{t}/snooze", data={"days": "30"})
    assert f'action="/trackers/{t}/unsnooze"' in client.get(f"/trackers/{t}").text


def test_someone_elses_or_a_missing_tracker_is_not_found(client, emailer, clean_engine):
    theirs = setup(client, emailer, clean_engine, email="owner@example.com")
    client.post("/logout")
    setup(client, emailer, clean_engine, email="intruder@example.com")
    assert client.get(f"/trackers/{theirs}").status_code == 404
    assert client.get("/trackers/999999").status_code == 404


def test_signed_out_visitors_go_home(client):
    response = client.get("/trackers/1")
    assert (response.status_code, response.headers["location"]) == (303, "/")


def test_a_removed_destination_is_not_found(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    assert client.get(f"/trackers/{t}").status_code == 200
    with session_scope(clean_engine) as s:
        s.get(Tracker, t).active = False
    page = client.get(f"/trackers/{t}")
    assert page.status_code == 404 and "No such destination." in page.text


def test_ids_beyond_the_database_range_are_a_styled_400(client, emailer, clean_engine):
    setup(client, emailer, clean_engine)
    page = client.get("/trackers/3000000000")
    assert page.status_code == 400 and 'href="/static/app.css?v=' in page.text
    assert client.post("/trackers/3000000000/snooze", data={"days": "30"}).status_code == 400
    assert client.post("/trackers/3000000000/unsnooze").status_code == 400


def test_the_intro_names_the_season_only_when_every_option_shares_it(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, t, 603, run_date=TODAY)
    assert "Mild (~16°C) but rainy and changeable" in client.get(f"/trackers/{t}").text
    add_candidate(
        clean_engine,
        t,
        700,
        run_date=TODAY,
        depart=TODAY.replace(month=10, day=8),
        ret=TODAY.replace(month=10, day=17),
    )
    page = client.get(f"/trackers/{t}").text
    assert "$700" in page and "Mild (~16°C)" not in page and "Warm sea" not in page
    assert "cheapest first. Prices are per person" in page


def test_a_snoozed_destination_with_no_prices_is_not_being_watched(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    assert "First prices after the next daily scan" in client.get(f"/trackers/{t}").text
    client.post(f"/trackers/{t}/snooze", data={"days": "30"})
    for url in ("/", f"/trackers/{t}"):
        page = client.get(url).text
        assert "Not watching while snoozed." in page and "First prices after" not in page


def test_snoozing_from_the_destination_page_returns_there(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    assert f'name="next" value="/trackers/{t}"' in client.get(f"/trackers/{t}").text
    r = client.post(f"/trackers/{t}/snooze", data={"days": "30", "next": f"/trackers/{t}"})
    assert r.headers["location"] == f"/trackers/{t}"
    assert f'name="next" value="/trackers/{t}"' in client.get(f"/trackers/{t}").text
    r = client.post(f"/trackers/{t}/unsnooze", data={"next": f"/trackers/{t}"})
    assert r.headers["location"] == f"/trackers/{t}"


def test_the_next_field_cannot_redirect_off_site(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    for bad in ("https://evil.example", "//evil.example", "/trackers/1/../../x", "/trackers/12x"):
        assert client.post(f"/trackers/{t}/snooze", data={"next": bad}).headers["location"] == "/"
        assert client.post(f"/trackers/{t}/unsnooze", data={"next": bad}).headers["location"] == "/"
    assert client.post(f"/trackers/{t}/unsnooze").headers["location"] == "/"


# --- booking from a deal, and fit notes ----------------------------------------------------------

BOTH = {**PROFILE_FORM, "tracker_dest_1": "MADEIRA", "tracker_min_1": "6", "tracker_max_1": "9"}


def two_trackers(client, emailer, engine, email="nick@example.com"):
    from ptopilot.db.models import User

    sign_in(client, emailer, engine, email)
    seed_profile(engine, BOTH, email)
    with session_scope(engine) as s:
        ids = {t.destination_code: t.id for t in s.scalars(select(Tracker))}
        return ids, s.scalar(select(User.id).where(User.email == email))


def test_booking_from_the_destination_page(client, emailer, clean_engine):
    from decimal import Decimal

    from ptopilot.db.models import PlannedTrip

    t = setup(client, emailer, clean_engine)
    c = add_candidate(clean_engine, t, 603, run_date=TODAY)
    assert f'action="/trackers/{t}/book"' in client.get(f"/trackers/{t}").text
    r = client.post(f"/trackers/{t}/book", data={"candidate_id": c})
    assert (r.status_code, r.headers["location"]) == (303, "/plan/2027?saved=booked")
    with session_scope(clean_engine) as s:
        trip = s.scalar(select(PlannedTrip).where(PlannedTrip.tracker_id == t, PlannedTrip.year == 2027))
        assert (trip.booked_depart, trip.booked_return) == (TODAY.replace(day=5), TODAY.replace(day=14))
        assert (trip.booked_price, trip.booked_pto) == (Decimal(603), 5)


def test_booking_another_users_candidate_is_a_404(client, emailer, clean_engine):
    from ptopilot.db.models import PlannedTrip

    theirs = setup(client, emailer, clean_engine, email="owner@example.com")
    c = add_candidate(clean_engine, theirs, 603, run_date=TODAY)
    client.post("/logout")
    mine = setup(client, emailer, clean_engine, email="intruder@example.com")
    assert client.post(f"/trackers/{theirs}/book", data={"candidate_id": c}).status_code == 404
    assert client.post(f"/trackers/{mine}/book", data={"candidate_id": c}).status_code == 404
    with session_scope(clean_engine) as s:
        assert s.scalar(select(PlannedTrip.id).where(PlannedTrip.booked_depart.is_not(None))) is None


def test_booking_a_clashing_deal_shows_the_message(client, emailer, clean_engine):
    from tests.digest.conftest import book

    ids, uid = two_trackers(client, emailer, clean_engine)
    book(clean_engine, uid, ids["MADEIRA"], TODAY.replace(day=8), TODAY.replace(day=12))
    c = add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY)
    r = client.post(f"/trackers/{ids['AZORES']}/book", data={"candidate_id": c})
    assert r.status_code == 400 and "Overlaps your booked Madeira trip." in r.text


def test_option_rows_show_fit_notes(client, emailer, clean_engine):
    from tests.digest.conftest import book

    ids, uid = two_trackers(client, emailer, clean_engine)
    # Madeira booked Mar 10-12 with 13 PTO leaves 15 - 13 = 2 days; the Azores trip needs 5.
    book(clean_engine, uid, ids["MADEIRA"], TODAY.replace(day=10), TODAY.replace(day=12), pto_cost=13)
    add_candidate(clean_engine, ids["AZORES"], 603, run_date=TODAY)  # Mar 5-14: overlaps
    add_candidate(
        clean_engine, ids["AZORES"], 700, run_date=TODAY, depart=date(2027, 3, 19), ret=date(2027, 3, 21)
    )
    text = client.get(f"/trackers/{ids['AZORES']}").text
    assert "Overlaps your booked Madeira trip." in text
    assert "remaining PTO (2 left)." in text
    assert text.count("Overlaps your booked") == 1


def test_a_deal_in_a_year_without_a_planning_year_has_no_pto_note(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, t, 603, run_date=TODAY, depart=date(2030, 3, 5), ret=date(2030, 3, 14))
    text = client.get(f"/trackers/{t}").text
    assert "remaining PTO" not in text and "I booked this" in text


def test_destination_page_greys_out_ruled_out_rows_with_their_reason(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    ok = add_candidate(clean_engine, t, 700, run_date=TODAY)
    bad = add_candidate(
        clean_engine, t, 400, run_date=TODAY, depart=TODAY.replace(day=12), ret=TODAY.replace(day=21)
    )
    set_verdict(clean_engine, bad, "ruled_out", "11h layover in Madrid")
    text = client.get(f"/trackers/{t}").text
    assert text.count('<tr class="dimmed">') == 1
    assert "11h layover in Madrid" in text
    assert f'value="{bad}"' not in text and f'value="{ok}"' in text  # no booking button on the ruled-out row
    assert text.count("I booked this") == 1


def test_forgiven_rows_show_their_trade_off(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    c = add_candidate(clean_engine, t, 400, run_date=TODAY)
    note = "6h layover in Madrid (worth it at 45% below typical)"
    set_verdict(clean_engine, c, "forgiven", note)
    text = client.get(f"/trackers/{t}").text
    assert f'<div class="fit-note">{note}</div>' in text
    assert '<tr class="dimmed">' not in text and "I booked this" in text
