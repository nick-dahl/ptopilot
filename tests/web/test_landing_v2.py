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
