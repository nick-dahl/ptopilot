"""The year planner page: trips with a bottom line, the year's PTO, the calendar and range rows."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from ptopilot.db.models import (
    Candidate,
    PlannedTrip,
    PlanningYear,
    RouteBaseline,
    RouteQuery,
    Tracker,
    TrackerRouteLink,
    TravelWindow,
    User,
)
from ptopilot.db.session import session_scope
from tests.web.conftest import PROFILE_FORM, TODAY, invite, sign_in

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
    monkeypatch.setattr("ptopilot.plan_totals.estimate_pto", lambda *a, **k: 6)
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
        "ptopilot.plan_totals.estimate_pto",
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


def test_a_holiday_inside_a_range_is_both_open_and_holiday(signed_in, clean_engine):
    uid = start_year(clean_engine)
    with session_scope(clean_engine) as s:
        s.add(TravelWindow(user_id=uid, start_date=date(2027, 7, 1), end_date=date(2027, 7, 9)))
    html = signed_in.get(f"/plan/{YEAR}").text
    got = classes(html, "2027-07-05")[0]
    assert "hol" in got and "open" in got
    css = (Path(__file__).parents[2] / "ptopilot/web/static/app.css").read_text(encoding="utf-8")
    assert ".day.open.hol" in css


def test_out_of_range_years_and_too_many_ranges_are_400s(signed_in, clean_engine):
    start_year(clean_engine)
    assert signed_in.get("/plan/99999999999").status_code == 400
    assert (
        signed_in.post("/plan/99999999999/pto", data={"pto_days": "1", "other_time_off": "0"}).status_code
        == 400
    )
    many = {f"range_start_{i}": "" for i in range(51)} | {f"range_end_{i}": "" for i in range(51)}
    r = signed_in.post(f"/plan/{YEAR}/ranges", data=many)
    assert r.status_code == 400
    assert "Too many ranges" in r.text


def test_plan_page_loads_the_planner_script(signed_in, clean_engine):
    start_year(clean_engine)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert '<script src="/static/planner.js" defer></script>' in html
    assert 'id="year-calendar"' in html
    assert 'id="ranges-form"' in html
    assert 'class="day' in html and 'tabindex="0"' in html
    assert html.count("tabindex=") == html.count("data-date=")


def test_the_planner_script_is_served(client):
    r = client.get("/static/planner.js")
    assert r.status_code == 200
    assert r.headers["content-type"].split(";")[0] in ("application/javascript", "text/javascript")


def test_rows_as_the_script_posts_them_are_accepted(signed_in, clean_engine):
    uid = start_year(clean_engine)
    r = signed_in.post(
        f"/plan/{YEAR}/ranges",
        data={
            "range_start_0": "2027-03-01",
            "range_end_0": "2027-03-09",
            "range_start_1": "2027-03-13",
            "range_end_1": "2027-03-21",
        },
    )
    assert r.status_code == 303
    with session_scope(clean_engine) as s:
        rows = s.execute(
            select(TravelWindow.start_date, TravelWindow.end_date)
            .where(TravelWindow.user_id == uid)
            .order_by(TravelWindow.start_date)
        ).all()
    assert [tuple(x) for x in rows] == [
        (date(2027, 3, 1), date(2027, 3, 9)),
        (date(2027, 3, 13), date(2027, 3, 21)),
    ]
    # closing every day posts no rows at all, which clears the ranges
    assert signed_in.post(f"/plan/{YEAR}/ranges", data={}).status_code == 303
    with session_scope(clean_engine) as s:
        assert s.scalar(select(TravelWindow.id).where(TravelWindow.user_id == uid)) is None


def test_a_far_range_end_is_a_400_naming_the_row(signed_in, clean_engine):
    start_year(clean_engine)
    r = signed_in.post(
        f"/plan/{YEAR}/ranges",
        data={
            "range_start_0": "2027-02-01",
            "range_end_0": "2027-02-03",
            "range_start_1": "2027-03-01",
            "range_end_1": "9999-12-31",
        },
    )
    assert r.status_code == 400
    assert "range 2" in r.text
    assert signed_in.get(f"/plan/{YEAR}").status_code == 200


def test_the_page_exposes_a_range_that_runs_past_the_year_end(signed_in, clean_engine):
    uid = start_year(clean_engine)
    with session_scope(clean_engine) as s:
        s.add(TravelWindow(user_id=uid, start_date=date(2027, 12, 18), end_date=date(2028, 1, 3)))
        s.add(TravelWindow(user_id=uid, start_date=date(2027, 3, 1), end_date=date(2027, 3, 4)))
    html = signed_in.get(f"/plan/{YEAR}").text
    assert """data-spill='[["2027-12-18", "2028-01-03"]]'""" in html


def test_the_page_hints_that_typed_dates_yield_to_the_calendar(signed_in, clean_engine):
    start_year(clean_engine)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert "Typed dates are replaced by the calendar when you've changed it" in html.replace("&#39;", "'")


# --- booking ---


def book_row(engine, tracker_id, depart, ret, pto=3, price=None, year=YEAR):
    with session_scope(engine) as s:
        trip = s.scalar(
            select(PlannedTrip).where(PlannedTrip.tracker_id == tracker_id, PlannedTrip.year == year)
        )
        trip.booked_depart, trip.booked_return, trip.booked_pto = depart, ret, pto
        trip.booked_price, trip.booked_currency = price, ("USD" if price is not None else None)


def my_uid(engine):
    with session_scope(engine) as s:
        return s.scalar(select(User.id).where(User.email == "nick@example.com"))


def test_planner_shows_a_booked_row_with_real_days_and_pto(signed_in, clean_engine, monkeypatch):
    uid = start_year(clean_engine, pto=20, other=5)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    add_trip(clean_engine, uid, "AZORES", 8)
    book_row(clean_engine, tid, date(2027, 5, 28), date(2027, 6, 5), pto=4, price=Decimal("802"))
    monkeypatch.setattr("ptopilot.plan_totals.estimate_pto", lambda *a, **k: 6)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert "Booked · May 28–Jun 5 · $802" in html
    assert f'action="/plan/{YEAR}/trips/{tid}/cancel"' in html
    assert "Cancel booking" in html
    assert "I booked this" in html  # the unbooked Azores row
    assert "Mark booked" in html
    # 9 days away booked + 8 target; 4 booked + 6 planned PTO; 15 available
    assert "2 trips · 17 days away · 10 PTO" in html
    assert "You have 15 · 4 booked · 5 free" in html


def test_booked_row_without_a_price_omits_it(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    book_row(clean_engine, tid, date(2027, 5, 28), date(2027, 6, 5), pto=4)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert "Booked · May 28–Jun 5<" in html


def test_over_budget_bottom_line_says_over(signed_in, clean_engine, monkeypatch):
    uid = start_year(clean_engine, pto=10, other=5)
    add_trip(clean_engine, uid, "LIS", 10)
    monkeypatch.setattr("ptopilot.plan_totals.estimate_pto", lambda *a, **k: 8)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert "You have 5 · 0 booked · 3 over" in html


def test_manual_booking_from_the_planner(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    r = signed_in.post(
        f"/plan/{YEAR}/trips/{tid}/book",
        data={"depart": "2027-05-28", "return": "2027-06-05", "price": "$1,234"},
    )
    assert (r.status_code, r.headers["location"]) == (303, f"/plan/{YEAR}?saved=booked")
    with session_scope(clean_engine) as s:
        trip = s.scalar(select(PlannedTrip).where(PlannedTrip.tracker_id == tid))
        assert (trip.booked_depart, trip.booked_return) == (date(2027, 5, 28), date(2027, 6, 5))
        assert (trip.booked_price, trip.booked_currency) == (Decimal("1234"), "USD")
        assert trip.booked_pto is not None
    blank = signed_in.post(
        f"/plan/{YEAR}/trips/{tid}/book", data={"depart": "2027-06-01", "return": "2027-06-03", "price": ""}
    )
    assert blank.status_code == 303
    with session_scope(clean_engine) as s:
        assert s.scalar(select(PlannedTrip.booked_price).where(PlannedTrip.tracker_id == tid)) is None


def test_manual_booking_with_a_bad_price_or_dates_is_a_400(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    url = f"/plan/{YEAR}/trips/{tid}/book"
    r = signed_in.post(url, data={"depart": "2027-05-28", "return": "2027-06-05", "price": "cheap"})
    assert r.status_code == 400
    assert "Enter a price like 802, or leave it blank." in r.text
    assert signed_in.post(url, data={"depart": "nope", "return": "2027-06-05"}).status_code == 400
    assert signed_in.post(url, data={"depart": "2027-06-05", "return": "2027-05-28"}).status_code == 400
    with session_scope(clean_engine) as s:
        assert s.scalar(select(PlannedTrip.booked_depart).where(PlannedTrip.tracker_id == tid)) is None


def test_manual_booking_that_overlaps_is_a_400(signed_in, clean_engine):
    uid = start_year(clean_engine)
    first = add_trip(clean_engine, uid, "LIS", 10)
    second = add_trip(clean_engine, uid, "AZORES", 8)
    book_row(clean_engine, first, date(2027, 5, 28), date(2027, 6, 5))
    r = signed_in.post(
        f"/plan/{YEAR}/trips/{second}/book", data={"depart": "2027-06-03", "return": "2027-06-10"}
    )
    assert r.status_code == 400
    assert "Overlaps your booked Lisbon trip." in r.text
    with session_scope(clean_engine) as s:
        assert s.scalar(select(PlannedTrip.booked_depart).where(PlannedTrip.tracker_id == second)) is None


def test_cancelling_a_booking_restores_watching_and_totals(signed_in, clean_engine, monkeypatch):
    uid = start_year(clean_engine, pto=20, other=5)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    monkeypatch.setattr("ptopilot.plan_totals.estimate_pto", lambda *a, **k: 6)
    book_row(clean_engine, tid, date(2027, 5, 28), date(2027, 6, 5), pto=4)
    assert "You have 15 · 4 booked · 11 free" in signed_in.get(f"/plan/{YEAR}").text
    r = signed_in.post(f"/plan/{YEAR}/trips/{tid}/cancel")
    assert r.status_code == 303
    html = signed_in.get(f"/plan/{YEAR}").text
    assert "Cancel booking" not in html
    assert "Watching" in html
    assert "You have 15 · 0 booked · 9 free" in html


def test_wont_fit_counts_booked_trips_first(signed_in, clean_engine, monkeypatch):
    uid = start_year(clean_engine, pto=20, other=5)  # 15 available
    add_trip(clean_engine, uid, "LIS", 8, priority=1)
    booked_later = add_trip(clean_engine, uid, "AZORES", 8, priority=3)
    book_row(clean_engine, booked_later, date(2027, 5, 28), date(2027, 6, 5), pto=10)
    monkeypatch.setattr("ptopilot.plan_totals.estimate_pto", lambda *a, **k: 7)
    html = signed_in.get(f"/plan/{YEAR}").text
    # 15 - 10 booked = 5 left; the planned 7 does not fit even though it ranks first
    assert "Won't fit: 5 PTO left after the others" in html


def test_calendar_marks_booked_days(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    book_row(clean_engine, tid, date(2027, 7, 2), date(2027, 7, 6))
    html = signed_in.get(f"/plan/{YEAR}").text
    for d in ("2027-07-02", "2027-07-06"):
        css, cell = classes(html, d)
        assert "booked" in css
        assert 'title="Lisbon (booked)"' in cell
    assert "booked" not in classes(html, "2027-07-01")[0]
    assert "booked" not in classes(html, "2027-07-07")[0]
    assert "hol" in classes(html, "2027-07-05")[0]  # the holiday stays marked inside the trip


def test_book_and_cancel_routes_are_scoped(signed_in, clean_engine):
    start_year(clean_engine)
    _, others_tid = other_user(clean_engine)
    data = {"depart": "2027-05-28", "return": "2027-06-05"}
    assert signed_in.post(f"/plan/{YEAR}/trips/{others_tid}/book", data=data).status_code == 404
    assert signed_in.post(f"/plan/{YEAR}/trips/{others_tid}/cancel").status_code == 404
    with session_scope(clean_engine) as s:
        assert s.scalar(select(PlannedTrip.booked_depart).where(PlannedTrip.tracker_id == others_tid)) is None
    mine = add_trip(clean_engine, my_uid(clean_engine), "AZORES", 8, year=2028)  # planned in another year
    assert signed_in.post(f"/plan/{YEAR}/trips/{mine}/book", data=data).status_code == 404
    assert signed_in.post(f"/plan/{YEAR}/trips/{mine}/cancel").status_code == 404


def fantastic_offer(engine, tracker_id, uid, dest, depart, price, season="good"):
    """One of today's offers: a week away, typical price 1000 for its route and month."""
    ret = depart.replace(day=depart.day + 6)
    with session_scope(engine) as s:
        rq = RouteQuery(
            origin="JFK", dest_airport=dest, return_airport=dest, depart_date=depart, return_date=ret
        )
        s.add(rq)
        s.flush()
        s.add(
            TrackerRouteLink(
                tracker_id=tracker_id,
                route_query_id=rq.id,
                run_date=TODAY,
                evening_departure=False,
                pto_cost=3,
                days_away=7,
                efficiency=2.0,
                month=depart.month,
                season_rating=season,
                days_off=[],
            )
        )
        s.add(
            Candidate(
                user_id=uid,
                tracker_id=tracker_id,
                route_query_id=rq.id,
                run_date=TODAY,
                evening_departure=False,
                price=Decimal(price),
                currency="USD",
                deal_level="good",
                go_now=50,
                confidence="normal",
                verified=True,
            )
        )
        if not s.scalar(
            select(RouteBaseline.origin).where(
                RouteBaseline.dest_airport == dest, RouteBaseline.month == depart.replace(day=1)
            )
        ):
            s.add(
                RouteBaseline(
                    origin="JFK",
                    dest_airport=dest,
                    return_airport=dest,
                    month=depart.replace(day=1),
                    length_bucket="week",
                    median=1000,
                    sigma=50,
                    n=30,
                    confidence="normal",
                )
            )


def test_planner_shows_combinations_only_when_fantastic(signed_in, clean_engine):
    uid = start_year(clean_engine, pto=20, other=5)
    lis = add_trip(clean_engine, uid, "LIS", 7)
    azo = add_trip(clean_engine, uid, "AZORES", 7)
    assert "Fantastic on every leg" not in signed_in.get(f"/plan/{YEAR}").text
    fantastic_offer(clean_engine, lis, uid, "LIS", date(2027, 5, 3), 700)
    fantastic_offer(clean_engine, azo, uid, "PDL", date(2027, 8, 2), 850)  # only 15% below
    assert "Fantastic on every leg" not in signed_in.get(f"/plan/{YEAR}").text
    fantastic_offer(clean_engine, azo, uid, "PDL", date(2027, 9, 6), 750)
    html = signed_in.get(f"/plan/{YEAR}").text
    assert "Fantastic on every leg" in html
    assert "<b>Lisbon</b>" in html and "30% below" in html and "25% below" in html
    assert "6 PTO of 15 left · saves ~$550 against typical" in html
    with session_scope(clean_engine) as s:  # a booked destination leaves the search
        s.execute(
            PlannedTrip.__table__.update()
            .where(PlannedTrip.tracker_id == azo)
            .values(booked_depart=date(2027, 12, 1), booked_return=date(2027, 12, 5), booked_pto=2)
        )
    assert "Fantastic on every leg" not in signed_in.get(f"/plan/{YEAR}").text


def _candidate_id(engine, tracker_id):
    with session_scope(engine) as s:
        return s.scalar(select(Candidate.id).where(Candidate.tracker_id == tracker_id))


def test_removing_a_destination_booked_this_year_is_refused(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 10)
    book_row(clean_engine, tid, date(2027, 5, 28), date(2027, 6, 5))
    r = signed_in.post(f"/destinations/{tid}/remove", follow_redirects=False)
    assert r.status_code == 400
    assert "Cancel your Lisbon booking first." in r.text
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).active is True
    assert "Lisbon" in signed_in.get(f"/plan/{YEAR}").text


def test_removing_a_destination_booked_only_in_a_past_year_works(signed_in, clean_engine):
    uid = start_year(clean_engine, year=2026)
    tid = add_trip(clean_engine, uid, "LIS", 10, year=2026)
    book_row(clean_engine, tid, date(2026, 5, 28), date(2026, 6, 5), year=2026)
    assert signed_in.post(f"/destinations/{tid}/remove", follow_redirects=False).status_code == 303
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tid).active is False


def test_booking_a_candidate_of_a_removed_destination_is_a_404(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 7)
    fantastic_offer(clean_engine, tid, uid, "LIS", date(2027, 5, 3), 700)
    cid = _candidate_id(clean_engine, tid)
    assert signed_in.post(f"/destinations/{tid}/remove", follow_redirects=False).status_code == 303
    r = signed_in.post(f"/trackers/{tid}/book", data={"candidate_id": cid}, follow_redirects=False)
    assert r.status_code == 404
    with session_scope(clean_engine) as s:
        assert s.scalar(select(PlannedTrip.booked_depart).where(PlannedTrip.tracker_id == tid)) is None


def test_a_booked_row_has_no_remove_and_refuses_it(signed_in, clean_engine):
    uid = start_year(clean_engine)
    booked = add_trip(clean_engine, uid, "LIS", 10)
    add_trip(clean_engine, uid, "AZORES", 8)
    book_row(clean_engine, booked, date(2027, 5, 28), date(2027, 6, 5))
    html = signed_in.get(f"/plan/{YEAR}").text
    assert f'action="/plan/{YEAR}/trips/{booked}/remove"' not in html
    assert html.count("/remove") == 1  # the unbooked Azores row keeps its Remove
    r = signed_in.post(f"/plan/{YEAR}/trips/{booked}/remove", follow_redirects=False)
    assert r.status_code == 400
    assert "Cancel the booking first." in r.text
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, booked).active is True
        assert s.scalar(select(PlannedTrip.booked_depart).where(PlannedTrip.tracker_id == booked))


def test_a_booked_only_destination_says_booked_not_first_prices(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 7)
    book_row(clean_engine, tid, date(2027, 5, 28), date(2027, 6, 5), price=Decimal("802"))
    dash = signed_in.get("/").text
    assert "Booked May 28–Jun 5" in dash
    assert "First prices after the next daily scan." not in dash
    page = signed_in.get(f"/trackers/{tid}").text
    assert "Booked May 28–Jun 5 · $802" in page
    assert "Booked: no more searches for 2027." in page
    assert "First prices after the next daily scan." not in page


def test_the_booked_line_omits_an_unknown_price(signed_in, clean_engine):
    uid = start_year(clean_engine)
    tid = add_trip(clean_engine, uid, "LIS", 7)
    book_row(clean_engine, tid, date(2027, 5, 28), date(2027, 6, 5))
    page = signed_in.get(f"/trackers/{tid}").text
    assert "Booked May 28–Jun 5" in page
    assert "Booked May 28–Jun 5 ·" not in page


def test_a_tracker_with_an_unknown_destination_does_not_break_the_planner(signed_in, clean_engine):
    uid = start_year(clean_engine)
    lis = add_trip(clean_engine, uid, "LIS", 7)
    ghost = add_trip(clean_engine, uid, "NOWHERE_XX", 7)
    fantastic_offer(clean_engine, lis, uid, "LIS", date(2027, 5, 3), 700)
    fantastic_offer(clean_engine, ghost, uid, "XXX", date(2027, 8, 3), 700)
    r = signed_in.get(f"/plan/{YEAR}")
    assert r.status_code == 200
    assert "Lisbon" in r.text
