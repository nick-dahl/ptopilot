"""The profile page's inputs: chips, segmented cards, the trip-length slider, and per-section saves."""

import html
import re
from html.parser import HTMLParser

from sqlalchemy import select

from ptopilot.db.models import User
from ptopilot.db.session import session_scope
from ptopilot.web.forms import merge_section
from tests.web.conftest import seed_profile, sign_in

JSON = {"Accept": "application/json"}


class Forms(HTMLParser):
    """What a browser without JavaScript would submit from each form on the page."""

    def __init__(self):
        super().__init__()
        self.forms: list[dict] = []
        self._select = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms.append({"attrs": a, "fields": [], "submit": None})
            return
        if not self.forms or "disabled" in a:
            return
        fields = self.forms[-1]["fields"]
        if tag == "input" and a.get("name"):
            kind = a.get("type", "text")
            if kind in ("checkbox", "radio") and "checked" not in a:
                return
            fields.append((a["name"], a.get("value", "on" if kind == "checkbox" else "")))
        elif tag == "button" and a.get("name") and self.forms[-1]["submit"] is None:
            self.forms[-1]["submit"] = (a["name"], a.get("value", ""))
        elif tag == "select":
            self._select = a.get("name")
        elif tag == "option" and self._select and "selected" in a:
            fields.append((self._select, a.get("value", "")))

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None


def profile_forms(client) -> list[dict]:
    parser = Forms()
    parser.feed(client.get("/profile").text)
    return [f for f in parser.forms if f["attrs"].get("action") == "/profile"]


def submitted(form: dict) -> dict[str, str]:
    data = dict(form["fields"])
    if form["submit"]:
        data[form["submit"][0]] = form["submit"][1]
    return data


def user_row(engine) -> dict:
    with session_scope(engine) as s:
        u = s.scalar(select(User))
        return {
            k: getattr(u, k)
            for k in (
                "home_airport", "nearby_airports", "holiday_calendar", "ignored_holidays", "extra_days_off",
                "pto_days_total", "pto_committed", "min_trip_days", "max_trip_days", "ideal_trip_days",
                "weather_tolerance", "max_stops_short", "max_stops_long", "allow_overnight_layover",
                "friday_evening_departure", "friday_evening_min_time",
            )
        }  # fmt: skip


def signed_in_with_profile(client, emailer, engine, **form):
    sign_in(client, emailer, engine)
    seed_profile(engine, {"ideal_trip_days": "10", "extra_days_off": "2027-12-24", **form})


def test_profile_page_has_the_three_in_place_sections(client, emailer, clean_engine):
    signed_in_with_profile(client, emailer, clean_engine)
    page = client.get("/profile").text
    for heading in ("Airports", "Time off", "Travel style"):
        assert f"<h2>{heading}</h2>" in page
    forms = profile_forms(client)
    assert len(forms) == 3
    assert all("data-inplace" in f["attrs"] and f["attrs"]["method"] == "post" for f in forms)
    assert '<script type="module" src="/static/chips.js"></script>' in page
    assert '<script type="module" src="/static/range.js"></script>' in page
    # Saved airports are chips: a list with a remove button per code
    assert re.search(r'<ul class="chip-list"[^>]*>', page)
    assert 'aria-label="Remove EWR"' in page and 'aria-label="Remove PHL"' in page
    assert 'data-source="airports"' in page and 'aria-label="Remove Columbus Day"' in page
    assert 'type="range"' in page and "No preference" in page


def test_profile_form_posts_without_js(client, emailer, clean_engine):
    """Each section's form, as a browser without JS submits it, saves and changes nothing."""
    signed_in_with_profile(client, emailer, clean_engine)
    before = user_row(clean_engine)
    forms = profile_forms(client)
    for form in forms:
        response = client.post("/profile", data=submitted(form))
        assert response.status_code == 303, response.text
        assert response.headers["location"] == "/profile?saved=1"
        assert user_row(clean_engine) == before
    # All sections together are one full form, as today
    everything = {k: v for f in forms for k, v in submitted(f).items() if k != "section"}
    assert client.post("/profile", data=everything).status_code == 303
    assert user_row(clean_engine) == before
    # The visible text field of a chip input is what a no-JS edit changes
    airports = submitted(forms[0])
    assert airports["nearby_airports"] == "EWR, PHL"
    client.post("/profile", data={**airports, "nearby_airports": "EWR"})
    assert user_row(clean_engine)["nearby_airports"] == ["EWR"]
    assert "Saved" in client.get("/profile?saved=1").text


def test_unknown_airport_codes_are_refused(client, emailer, clean_engine):
    signed_in_with_profile(client, emailer, clean_engine)
    response = client.post("/profile", data={"section": "airports", "nearby_airports": "ZZZ"}, headers=JSON)
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False and any("ZZZ" in e for e in body["errors"])
    page = client.post("/profile", data={"section": "airports", "nearby_airports": "ZZZ"})
    assert page.status_code == 400 and "ZZZ" in page.text
    assert user_row(clean_engine)["nearby_airports"] == ["EWR", "PHL"]


def test_a_section_saves_on_its_own(client, emailer, clean_engine):
    signed_in_with_profile(client, emailer, clean_engine)
    before = user_row(clean_engine)
    response = client.post("/profile", data={"weather_tolerance": "strict"}, headers=JSON)
    assert response.status_code == 200 and response.json()["ok"] is True
    assert user_row(clean_engine) == {**before, "weather_tolerance": "strict"}
    # A named section that leaves a switch out turns it off; other sections' switches are untouched
    response = client.post(
        "/profile",
        data={
            "section": "travel",
            "min_trip_days": "7",
            "max_trip_days": "16",
            "weather_tolerance": "strict",
        },
        headers=JSON,
    )
    assert response.json()["ok"] is True
    after = user_row(clean_engine)
    assert after["allow_overnight_layover"] is False and after["friday_evening_departure"] is False
    assert after["pto_committed"] == before["pto_committed"] and after["home_airport"] == "JFK"


def test_merge_section_overlays_the_submitted_fields():
    current = {"home_airport": "JFK", "weather_tolerance": "normal", "allow_overnight_layover": "on"}
    assert merge_section(current, {"weather_tolerance": "strict"}) == {
        **current,
        "weather_tolerance": "strict",
    }
    travel = merge_section(current, {"section": "travel", "weather_tolerance": "relaxed"})
    assert travel == {"home_airport": "JFK", "weather_tolerance": "relaxed"}
    assert merge_section(current, {"section": "airports"}) == current
    assert current["weather_tolerance"] == "normal"  # not changed in place


def test_section_errors_come_back_as_json(client, emailer, clean_engine):
    signed_in_with_profile(client, emailer, clean_engine)
    before = user_row(clean_engine)
    response = client.post(
        "/profile", data={"section": "travel", "min_trip_days": "12", "max_trip_days": "6"}, headers=JSON
    )
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False and any("min_trip_days/max_trip_days" in e for e in body["errors"])
    assert user_row(clean_engine) == before


def radio_options(page: str, name: str) -> list[tuple[str, str]]:
    pattern = rf'name="{name}" value="([^"]+)"[^>]*>\s*<span class="seg-label">([^<]+)</span>'
    return [(v, html.unescape(label).strip()) for v, label in re.findall(pattern, page)]


def test_weather_and_stops_map_to_the_existing_values(client, emailer, clean_engine):
    signed_in_with_profile(client, emailer, clean_engine, max_stops_short="1", max_stops_long="2")
    page = client.get("/profile").text
    assert radio_options(page, "weather_tolerance") == [
        ("strict", "Only the best months"),
        ("normal", "Shoulder season is fine"),
        ("relaxed", "Any time if it's cheap"),
    ]
    assert radio_options(page, "max_stops_short") == [
        ("0", "Nonstop only"),
        ("1", "Up to 1 stop"),
        ("2", "Up to 2 stops"),
    ]
    assert radio_options(page, "max_stops_long") == [("1", "Up to 1 stop"), ("2", "Up to 2 stops")]
    assert re.search(r'name="weather_tolerance" value="normal"[^>]*checked', page)
    assert re.search(r'name="max_stops_long" value="2"[^>]*checked', page)
    client.post(
        "/profile",
        data={"weather_tolerance": "relaxed", "max_stops_short": "0", "max_stops_long": "1"},
        headers=JSON,
    )
    row = user_row(clean_engine)
    assert (row["weather_tolerance"], row["max_stops_short"], row["max_stops_long"]) == ("relaxed", 0, 1)


def test_an_unusual_stored_stop_count_stays_selectable(client, emailer, clean_engine):
    signed_in_with_profile(client, emailer, clean_engine)  # the fixture's profile allows 3 stops
    page = client.get("/profile").text
    assert ("3", "Up to 3 stops") in radio_options(page, "max_stops_short")
    assert re.search(r'name="max_stops_short" value="3"[^>]*checked', page)


def test_no_preference_clears_the_ideal_length(client, emailer, clean_engine):
    signed_in_with_profile(client, emailer, clean_engine)
    assert user_row(clean_engine)["ideal_trip_days"] == 10
    page = client.get("/profile").text
    assert re.search(r'name="ideal_trip_days"[^>]*value="10"', page)
    response = client.post("/profile", data={"section": "travel", "ideal_trip_days": ""}, headers=JSON)
    assert response.json()["ok"] is True
    assert user_row(clean_engine)["ideal_trip_days"] is None
    page = client.get("/profile").text
    assert re.search(r'name="ideal_trip_days"[^>]*value=""', page)


def test_the_leave_after_work_time_sits_with_its_switch(client, emailer, clean_engine):
    signed_in_with_profile(client, emailer, clean_engine)
    page = client.get("/profile").text
    assert 'role="switch"' in page
    block = page[page.index('class="after-work"') :]
    assert block.index('name="friday_evening_departure"') < block.index('name="friday_evening_min_time"')
