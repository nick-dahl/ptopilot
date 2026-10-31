"""Deferred polish from Plan 7's review: styles live in the stylesheet, the footer follows the real schedule,
odd ids are plain 404s, error pages keep their headers, ruled-out destinations say so, pages load only the
baselines they show, and only web links become "View flights"."""

import re
from pathlib import Path

import yaml
from sqlalchemy import select

from ptopilot import config
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Candidate, Tracker
from ptopilot.db.session import session_scope
from ptopilot.digest.render import render
from ptopilot.digest.select import Digest, build_digests
from ptopilot.links import web_link
from ptopilot.pipeline.queries import load_baselines
from ptopilot.web.history import destination_summaries, trip_options
from tests.digest.conftest import RUN, add_baseline, add_candidate, add_tracker, add_user
from tests.digest.test_render import NOW, ROW, card
from tests.web.conftest import PROFILE_FORM, TODAY, seed_profile, sign_in

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "ptopilot" / "web" / "templates"
GEO, SEASONS = load_geo(), load_seasons()


def test_page_templates_have_no_fixed_inline_styles():
    """Fixed spacing and type belong in app.css; only data-driven values (destination colors, bar
    positions) may be inline. The email templates are exempt: email needs inline styles."""
    fixed = [
        f"{page.name}: {value}"
        for page in TEMPLATES.glob("*.html")
        for value in re.findall(r'style="([^"]*)"', page.read_text(encoding="utf-8"))
        if "{{" not in value
    ]
    assert fixed == []


def test_the_footer_names_the_days_the_digest_workflow_really_runs():
    cron = yaml.safe_load((ROOT / ".github" / "workflows" / "digest.yml").read_text(encoding="utf-8"))
    triggers = cron.get("on", cron.get(True))
    cron_days = triggers["schedule"][0]["cron"].split()[4]
    as_python_weekdays = tuple(sorted((int(d) - 1) % 7 for d in cron_days.split(",")))  # cron: 0 = Sunday
    assert as_python_weekdays == tuple(sorted(config.DIGEST_WEEKDAYS))


def test_the_footer_text_comes_from_the_schedule(monkeypatch):
    monkeypatch.setattr(config, "DIGEST_WEEKDAYS", (1, 4))
    _, html, text = render(Digest(1, "nick@example.com", RUN, [card()], [ROW]), now=NOW)
    assert "emails trip deals on Tuesdays and Fridays" in html and "on Tuesdays and Fridays" in text


def test_tracker_zero_and_negative_ids_are_plain_not_found(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    client.post("/profile", data=PROFILE_FORM)
    for path in ("/trackers/0", "/trackers/-5"):
        assert client.get(path).status_code == 404


def test_error_pages_keep_their_headers(client):
    response = client.get("/logout")  # POST-only route
    assert response.status_code == 405 and "POST" in response.headers.get("allow", "")
    assert response.headers["content-type"].startswith("text/html")
    assert "Method Not Allowed" in response.text


def test_a_destination_with_every_trip_ruled_out_says_so(clean_engine):
    user = add_user(clean_engine)
    t = add_tracker(clean_engine, user)
    c = add_candidate(clean_engine, t, 500)
    with session_scope(clean_engine) as s:
        s.get(Candidate, c).state = "excluded"
    (summary,) = destination_summaries(clean_engine, GEO, SEASONS, user, RUN)
    assert summary.best is None and summary.ruled_out is True


def test_the_dashboard_card_shows_the_ruled_out_note(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    seed_profile(clean_engine)
    with session_scope(clean_engine) as s:
        tracker_id = s.scalar(select(Tracker.id))
    c = add_candidate(clean_engine, tracker_id, 603, run_date=TODAY)
    with session_scope(clean_engine) as s:
        s.get(Candidate, c).state = "excluded"
    page = client.get("/").text
    assert "Every current trip is ruled out." in page and "$603" not in page


def test_load_baselines_can_be_limited_to_some_routes(clean_engine):
    add_baseline(clean_engine, 700)  # JFK-PDL
    add_baseline(clean_engine, 900, dest="FNC")
    with session_scope(clean_engine) as s:
        assert {k[1] for k in load_baselines(s)} == {"PDL", "FNC"}
        assert {k[1] for k in load_baselines(s, routes={("JFK", "FNC", "FNC")})} == {"FNC"}
        assert load_baselines(s, routes=set()) == {}


def test_trip_options_still_carry_their_baselines(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 603)
    add_baseline(clean_engine, 700)
    add_baseline(clean_engine, 900, dest="FNC")  # another route the page doesn't show
    (option,) = trip_options(clean_engine, GEO, SEASONS, t, RUN)
    assert option.median == 700 and option.bar is not None


def test_only_web_links_count():
    assert (
        web_link("https://www.google.com/travel/flights?tfs=X")
        == "https://www.google.com/travel/flights?tfs=X"
    )
    assert web_link("http://example.com/x") == "http://example.com/x"
    for bad in ("javascript:alert(1)", "data:text/html,x", "//evil.example", "", None, "ftp://x"):
        assert web_link(bad) is None


def test_non_web_deep_links_are_dropped_on_the_page_and_in_the_digest(clean_engine):
    from ptopilot.db.models import PriceObservation

    user = add_user(clean_engine)
    t = add_tracker(clean_engine, user)
    add_candidate(clean_engine, t, 603)
    with session_scope(clean_engine) as s:
        for obs in s.scalars(select(PriceObservation)):
            obs.deep_link = "javascript:alert(1)"
    (option,) = trip_options(clean_engine, GEO, SEASONS, t, RUN)
    (digest,) = build_digests(clean_engine, GEO, SEASONS, RUN)
    assert option.deep_link is None and digest.deals[0].deep_link is None


def test_pressed_holiday_chip_tick_is_a_css_escape():
    """The tick is written as an escape, so no encoding slip can garble it into stray characters."""
    css = (ROOT / "ptopilot" / "web" / "static" / "app.css").read_text(encoding="utf-8")
    rule = next(line for line in css.splitlines() if '.holiday-toggle[aria-pressed="true"]::before' in line)
    assert r'content: "\2713\00a0"' in rule
    assert rule.isascii()
