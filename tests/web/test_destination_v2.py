"""The livelier destination page (Plan 15): a photo header, a hoverable trend chart and a date grid."""

import re
from datetime import date, timedelta

from ptopilot.db.models import Candidate, Tracker
from ptopilot.db.session import session_scope
from tests.digest.conftest import add_baseline, add_candidate
from tests.digest.test_related_digest import add_check
from tests.web.conftest import TODAY
from tests.web.test_destination_page import setup


def section(page: str, id_: str) -> str:
    start = page.index(f'id="{id_}"')
    return page[start : page.index("</section>", start)]


def test_date_grid_with_no_trips_shows_an_empty_state(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    grid = section(client.get(f"/trackers/{t}").text, "date-grid")
    assert "First prices after the next daily scan." in grid and "<table" not in grid


def test_cells_link_to_their_trip_rows(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    add_candidate(clean_engine, t, 603, run_date=TODAY)
    add_candidate(clean_engine, t, 700, run_date=TODAY, depart=date(2027, 3, 12), ret=date(2027, 3, 20))
    add_baseline(clean_engine, 700)
    page = client.get(f"/trackers/{t}").text
    grid = section(page, "date-grid")
    keys = re.findall(r'href="#trip-([^"]+)"', grid)
    assert len(keys) == 2
    for key in keys:
        assert f'id="trip-{key}">' in section(page, "date-options")  # the row's first cell
    assert "Week of Mar 1" in grid and "Week of Mar 8" in grid
    assert "9 days" in grid and "10 days" in grid
    assert "$603" in grid and "$700" in grid


def test_dimmed_cells_say_so(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    c = add_candidate(clean_engine, t, 603, run_date=TODAY)
    with session_scope(clean_engine) as s:
        s.get(Candidate, c).state = "excluded"
    grid = section(client.get(f"/trackers/{t}").text, "date-grid")
    assert "is-dimmed" in grid and "unavailable" in grid


def test_chart_points_carry_date_and_price(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    for days_ago, price in [(0, 603), (1, 640), (2, 660)]:
        add_candidate(clean_engine, t, price, run_date=TODAY - timedelta(days=days_ago))
    page = client.get(f"/trackers/{t}").text
    assert 'data-date="2027-03-02" data-price="660"' in page
    assert 'data-date="2027-03-04" data-price="603"' in page
    assert '<script type="module" src="/static/chart.js"></script>' in page


def test_the_header_names_the_season_and_the_target_length(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    with session_scope(clean_engine) as s:
        s.get(Tracker, t).target_days = 9
    add_candidate(clean_engine, t, 603, run_date=TODAY)
    hero = section(client.get(f"/trackers/{t}").text.replace("</div>\n\n<div", "</section><div"), "dest-hero")
    assert "<h1>Azores</h1>" in hero and "~9 days away" in hero
    assert re.search(r"(Good season|Shoulder season|Off-season) in March", hero)


def test_the_header_shows_the_destination_photo(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)  # the Azores has a built-in photo
    hero = section(client.get(f"/trackers/{t}").text, "dest-hero")
    assert "cover has-photo" in hero and "Photo: " in hero


def test_related_deals_are_small_photo_cards(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    with session_scope(clean_engine) as s:
        tracker = s.get(Tracker, t)
        uid = tracker.user_id
    add_candidate(clean_engine, t, 900, run_date=TODAY, level="none", go_now=0)
    add_check(clean_engine, uid, t, run_date=TODAY)
    page = client.get(f"/trackers/{t}").text
    related = page[page.index("<h2>Related</h2>") :]
    assert "related-cover" in related and "has-photo" in related and "Madeira instead of Azores" in related


def test_a_snoozed_destinations_empty_grid_says_it_is_not_being_watched(client, emailer, clean_engine):
    t = setup(client, emailer, clean_engine)
    client.post(f"/trackers/{t}/snooze", data={"days": "30"})
    grid = section(client.get(f"/trackers/{t}").text, "date-grid")
    assert "Not watching while snoozed." in grid and "next daily scan" not in grid


def test_the_grid_box_contains_its_hidden_text_so_phones_never_scroll_sideways():
    """The cells' .sr-only text is position: absolute; the scrolling box must be its containing block, or
    that text escapes the overflow clip and widens the page (found in the 390 px browser check)."""
    from pathlib import Path

    css = (Path(__file__).resolve().parents[2] / "ptopilot" / "web" / "static" / "app.css").read_text("utf-8")
    rule = re.search(r"\.grid-scroll \{([^}]*)\}", css).group(1)
    assert "position: relative" in rule and "overflow-x: auto" in rule
