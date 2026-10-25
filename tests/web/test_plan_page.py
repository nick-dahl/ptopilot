"""The year planner page: trips with a bottom line, the year's PTO, the calendar and range rows."""

from datetime import date

import pytest
from sqlalchemy import delete, select

from ptopilot.db.models import PlannedTrip, PlanningYear, RouteBaseline, Tracker, TravelWindow, User
from ptopilot.db.session import session_scope
from tests.web.conftest import PROFILE_FORM, invite, sign_in

YEAR = 2027


@pytest.fixture
def signed_in(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    assert client.post("/profile", data=PROFILE_FORM).status_code == 303
    with session_scope(clean_engine) as s:  # the profile form seeds a 2027 year; each test sets up its own
        for table in (PlannedTrip, PlanningYear, Tracker, TravelWindow):
            s.execute(delete(table))
    return client


def start_year(engine, email="nick@example.com", year=YEAR, pto=20, other=5):
    with session_scope(engine) as s:
        uid = s.scalar(select(User.id).where(User.email == email))
        s.add(PlanningYear(user_id=uid, year=year, pto_days=pto, other_time_off=other))
        return uid


def add_trip(engine, uid, code, target, year=YEAR, priority=2):
    with session_scope(engine) as s:
        t = Tracker(
            user_id=uid,
            destination_code=code,
            min_stay_days=max(target - 3, 1),
            max_stay_days=target + 2,
            target_days=target,
            priority=priority,
        )
        s.add(t)
        s.flush()
        s.add(PlannedTrip(user_id=uid, year=year, tracker_id=t.id))
        return t.id


def other_user(engine):
    """A second user with their own planning year and trip."""
    invite(engine, "other@example.com")
    with session_scope(engine) as s:
        s.add(
            User(
                email="other@example.com",
                home_airport="LAX",
                country="US",
                holiday_calendar="US",
                pto_days_total=10,
                max_trip_days=16,
            )
        )
    uid = start_year(engine, "other@example.com", pto=11, other=1)
    return uid, add_trip(engine, uid, "LIS", 9)


def classes(html, d):
    start = html.index(f'data-date="{d}"')
    cell = html[html.rindex("<td", 0, start) : html.index("</td>", start)]
    return cell.split('class="')[1].split('"')[0].split(), cell


def test_plan_page_lists_trips_with_band_and_estimate(signed_in, clean_engine, monkeypatch):
    uid = start_year(clean_engine)
    add_trip(clean_engine, uid, "LIS", 10)
    monkeypatch.setattr("ptopilot.web.planner_view.estimate_pto", lambda *a, **k: 6)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert "Lisbon" in html
    assert 'value="10"' in html
    assert "searching 8–12" in html
    assert "Watching" in html
    assert "1 trip · 10 days away · 6 PTO" in html
    assert "You have 15" in html
    assert 'href="/destinations"' in html
    assert 'href="/plan" aria-current="page"' in html


def test_plan_page_marks_holidays_weekends_and_open_days(signed_in, clean_engine):
    uid = start_year(clean_engine)
    with session_scope(clean_engine) as s:
        s.add(TravelWindow(user_id=uid, start_date=date(2027, 3, 8), end_date=date(2027, 3, 10)))
    html = signed_in.get(f"/plan/{YEAR}").text
    assert "hol" in classes(html, "2027-07-05")[0]
    assert "Independence Day" in classes(html, "2027-07-05")[1]
    assert "we" in classes(html, "2027-07-03")[0]
    assert "open" in classes(html, "2027-03-09")[0]
    assert "open" not in classes(html, "2027-03-11")[0]
    assert "hol" not in classes(html, "2027-10-11")[0]  # Columbus Day is ignored in the profile
    assert html.count('data-date="') == 365


def test_bottom_line_totals_and_wont_fit_note(signed_in, clean_engine, monkeypatch):
    uid = start_year(clean_engine, pto=20, other=5)
    for code, priority in (("LIS", 1), ("AZORES", 2), ("MADEIRA", 3)):
        add_trip(clean_engine, uid, code, 8, priority=priority)
    estimates = {"LIS": 5, "AZORES": 6, "MADEIRA": 9}
    monkeypatch.setattr(
        "ptopilot.web.planner_view.estimate_pto",
        lambda profile, spec, *a, **k: estimates[spec.destination_code],
    )
    html = signed_in.get(f"/plan/{YEAR}").text
    assert html.count("Won't fit") == 1
    assert "Won't fit: 4 PTO left after the others" in html
    assert html.index("Madeira") < html.index("Won't fit")
    assert "3 trips · 24 days away · 20 PTO" in html


def test_saving_ranges_merges_and_redirects(signed_in, clean_engine):
    uid = start_year(clean_engine)
    r = signed_in.post(
        f"/plan/{YEAR}/ranges",
        data={
            "range_start_0": "2027-03-10",
            "range_end_0": "2027-03-20",
            "range_start_1": "2027-03-01",
            "range_end_1": "2027-03-09",
            "range_start_2": "",
            "range_end_2": "",
        },
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/plan/{YEAR}?saved=ranges"
    with session_scope(clean_engine) as s:
        rows = s.execute(
            select(TravelWindow.start_date, TravelWindow.end_date).where(TravelWindow.user_id == uid)
        ).all()
    assert [tuple(x) for x in rows] == [(date(2027, 3, 1), date(2027, 3, 20))]
    page = signed_in.get(r.headers["location"]).text
    assert 'value="2027-03-01"' in page
    assert 'value="2027-03-20"' in page
    assert page.count('type="date"') == 2 * (1 + 2)


def test_saving_a_reversed_range_is_a_400_naming_the_row(signed_in, clean_engine):
    uid = start_year(clean_engine)
    r = signed_in.post(
        f"/plan/{YEAR}/ranges",
        data={
            "range_start_0": "",
            "range_end_0": "",
            "range_start_1": "2027-03-20",
            "range_end_1": "2027-03-10",
        },
    )
    assert r.status_code == 400
    assert "range 2" in r.text
    assert 'value="2027-03-20"' in r.text
    r = signed_in.post(f"/plan/{YEAR}/ranges", data={"range_start_0": "nope", "range_end_0": "2027-03-10"})
    assert r.status_code == 400
    assert "range 1" in r.text
    with session_scope(clean_engine) as s:
        assert s.scalar(select(TravelWindow.id).where(TravelWindow.user_id == uid)) is None


def test_saving_pto_validates(signed_in, clean_engine):
    uid = start_year(clean_engine)
    r = signed_in.post(f"/plan/{YEAR}/pto", data={"pto_days": "25", "other_time_off": "3"})
    assert r.status_code == 303
    assert r.headers["location"] == f"/plan/{YEAR}?saved=pto"
    bad = signed_in.post(f"/plan/{YEAR}/pto", data={"pto_days": "5", "other_time_off": "9"})
    assert bad.status_code == 400
    assert "PTO must satisfy" in bad.text
    with session_scope(clean_engine) as s:
        py = s.get(PlanningYear, (uid, YEAR))
        assert (py.pto_days, py.other_time_off) == (25, 3)


def test_editing_a_target_and_removing_a_trip(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    assert signed_in.post(f"/plan/{YEAR}/trips/{tid}", data={"target_days": "14"}).status_code == 303
    assert signed_in.post(f"/plan/{YEAR}/trips/{tid}", data={"target_days": "1"}).status_code == 400
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).target_days == 14
    assert signed_in.post(f"/plan/{YEAR}/trips/{tid}/remove").status_code == 303
    with session_scope(clean_engine) as s:
        assert s.scalar(select(PlannedTrip.id).where(PlannedTrip.tracker_id == tid)) is None
    assert "Lisbon" not in signed_in.get(f"/plan/{YEAR}").text


def test_plan_redirects_to_the_current_year_or_to_new(signed_in, clean_engine):
    r = signed_in.get("/plan")
    assert (r.status_code, r.headers["location"]) == (303, "/plan/new")
    start_year(clean_engine, year=2028)
    start_year(clean_engine, year=2027)
    assert signed_in.get("/plan").headers["location"] == "/plan/2027"


def test_signed_out_visitors_go_home(client):
    pto = client.post("/plan/2027/pto", data={"pto_days": "1", "other_time_off": "0"})
    for r in (client.get("/plan"), client.get("/plan/2027"), pto):
        assert (r.status_code, r.headers["location"]) == (303, "/")


def test_plan_routes_are_scoped_to_the_signed_in_user(signed_in, clean_engine):
    mine = start_year(clean_engine)
    my_trip = add_trip(clean_engine, mine, "LIS", 10)
    their_id, their_trip = other_user(clean_engine)
    start_year(clean_engine, "other@example.com", year=2030)
    with session_scope(clean_engine) as s:
        s.add(PlanningYear(user_id=mine, year=2029, pto_days=3, other_time_off=0))
    # a year only the other user has
    assert signed_in.get("/plan/2030").status_code == 404
    assert signed_in.post("/plan/2030/pto", data={"pto_days": "1", "other_time_off": "0"}).status_code == 404
    assert signed_in.post("/plan/2030/ranges", data={}).status_code == 404
    # their tracker, in my year
    assert signed_in.post(f"/plan/{YEAR}/trips/{their_trip}", data={"target_days": "30"}).status_code == 404
    assert signed_in.post(f"/plan/{YEAR}/trips/{their_trip}/remove").status_code == 404
    # my tracker, but not planned in that year
    assert signed_in.post(f"/plan/2029/trips/{my_trip}", data={"target_days": "30"}).status_code == 404
    assert signed_in.post(f"/plan/2029/trips/{my_trip}/remove").status_code == 404
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, their_trip).target_days == 9
        assert s.get(Tracker, their_trip).active
        assert s.get(Tracker, my_trip).target_days == 10
        assert s.scalar(select(PlannedTrip.id).where(PlannedTrip.tracker_id == their_trip)) is not None
        assert s.scalar(
            select(PlannedTrip.id).where(PlannedTrip.tracker_id == my_trip, PlannedTrip.year == YEAR)
        )
        assert s.get(PlanningYear, (their_id, 2030)).pto_days == 20
        assert s.get(PlanningYear, (their_id, YEAR)).pto_days == 11


def test_plan_page_shows_building_history_and_too_short_notes(signed_in, clean_engine):
    uid = start_year(clean_engine)
    add_trip(clean_engine, uid, "LIS", 10)
    add_trip(clean_engine, uid, "TYO", 3)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert html.count("Building price history") == 2
    assert "Needs at least 7 days away" in html
    assert html.count("Needs at least") == 1
    with session_scope(clean_engine) as s:
        s.add(
            RouteBaseline(
                origin="JFK",
                dest_airport="LIS",
                return_airport="LIS",
                month=date(2027, 6, 1),
                length_bucket="week",
                median=500,
                sigma=50,
                n=30,
                confidence="normal",
            )
        )
    assert signed_in.get(f"/plan/{YEAR}").text.count("Building price history") == 1


def test_pages_other_than_plan_have_no_script_tag(signed_in):
    for url in ("/", "/destinations", "/profile"):
        assert "<script" not in signed_in.get(url).text
