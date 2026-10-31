"""The landing page (Plan 15 §3.7): a photo hero with the promise, sign-in, and real components."""

import re

from tests.web.conftest import is_landing

PROMISE = "Your time off, your places, the right fare."
LINE = (
    "ptopilot watches flights for the trips you want, fits them to your PTO, "
    "and tells you when a fare is worth taking."
)


def test_landing_has_the_promise_and_sign_in(client):
    page = client.get("/")
    assert is_landing(page)
    assert PROMISE in page.text and LINE in page.text
    assert 'method="post" action="/login"' in page.text and 'type="email"' in page.text


def test_landing_hero_is_a_built_in_photo_with_its_credit(client):
    from ptopilot.photos import builtin_photos

    page = client.get("/").text
    hero = page[page.index('class="cover has-photo landing-hero') :]
    photo = builtin_photos()["PATAGONIA"]
    assert photo.image_url in hero[:2000] and f"Photo: {photo.author}" in hero


def test_landing_examples_are_labelled(client):
    page = client.get("/").text
    assert page.count(">Example<") == 3
    for step in ("Mark your free dates", "Get the deals that fit", "Know when to move"):
        assert step in page


def test_landing_examples_are_the_real_components(client):
    page = client.get("/").text
    assert '<table class="month"' in page and "day we" in page and " open" in page  # the planner calendar
    assert 'class="dest-card"' in page and "below typical" in page  # a deal card
    assert 'class="tag tag-rare">Rare: likely gone within ~2 days' in page  # the Rare tag, its duration line
    assert page.count("has-photo") >= 3  # the example cards have their photos, not just the gradient


def test_landing_example_calendar_is_not_a_control(client):
    """It only illustrates: no tap targets that do nothing."""
    page = client.get("/").text
    calendar = page[page.index('<table class="month"') : page.index("</table>")]
    assert "data-date" not in calendar and "tabindex" not in calendar


def test_landing_makes_no_claims(client):
    page = client.get("/").text.casefold()
    for claim in ("users", "saved $", "testimonial", "trusted by", "customers"):
        assert claim not in page
    assert not re.search(r"save[sd]? (up to )?\$?\d", page)


def test_landing_links_credits(client):
    page = client.get("/").text
    footer = page[page.index('<footer class="site-footer"') :]
    assert 'href="/credits"' in footer


def test_landing_hero_credit_is_not_hover_only():
    """Touch has no hover: the hero's own rule shows the credit (spec §3.6)."""
    from pathlib import Path

    css = (Path(__file__).parents[2] / "ptopilot/web/static/app.css").read_text(encoding="utf-8")
    rules = re.findall(r"([^{}]*\.landing-hero[^{}]*\.cover-credit[^{}]*)\{([^}]*)\}", css)
    shown = [body for selector, body in rules if ":hover" not in selector and ":focus" not in selector]
    assert shown and all(re.search(r"opacity:\s*(\.[1-9]|0\.[1-9]|1)", body) for body in shown)


def test_landing_examples_are_always_ahead_of_today():
    """The example calendar and trips move with today, so they never show a trip in the past."""
    from datetime import date

    from ptopilot.data import load_geo
    from ptopilot.web.samples import example_trip, landing

    geo = load_geo()
    for month in range(1, 13):
        today = date(2026, month, 28)
        ex = landing(geo, today)
        depart, ret = example_trip(today)
        assert today < depart < ret and depart.month == ret.month and depart.weekday() == 4
        assert ex.deal.best.depart_date == depart and ex.rare.best.depart_date > ret
        name, weeks = ex.calendar[0]
        assert name.endswith(str(depart.year))
        assert [c["date"] for w in weeks for c in w if c and c["open"]][0] == depart
        assert 0 < ex.deal.best.pto_cost <= 7


def test_landing_page_shows_the_month_ahead_of_its_today(client):
    from ptopilot.web.samples import example_trip
    from tests.web.conftest import TODAY

    depart, _ = example_trip(TODAY)
    assert f"<caption>{depart.strftime('%B %Y')}</caption>" in client.get("/").text
