"""Hidden gems pages (Plan 16, spec section 3.6): /gems, the full guide, "Track this place", the nav and the
dashboard card. The catalogue is the fictional test fixtures."""

import re
import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from ptopilot import gems
from ptopilot.db.models import GemFare, GemIssue, PlacePhotoRow, Tracker, User
from ptopilot.db.session import session_scope
from ptopilot.web.gems_view import fit_pill
from tests.web.conftest import TODAY, seed_profile, sign_in
from tests.web.test_destinations_page import make_client  # noqa: F401  (fixture)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gems"
JSON = {"Accept": "application/json"}
OWN_PHOTO = "Example_coast.jpg"


@pytest.fixture(autouse=True)
def fixture_gems(monkeypatch):
    monkeypatch.setenv(gems.GEMS_DIR_ENV, str(FIXTURES))


def user_id(engine, email="nick@example.com") -> int:
    with session_scope(engine) as s:
        return s.scalar(select(User.id).where(User.email == email))


def signed_in(client, emailer, engine, email="nick@example.com") -> int:
    sign_in(client, emailer, engine, email)
    seed_profile(engine, email=email)
    return user_id(engine, email)


def issue(engine, uid, slug, published_on=TODAY):
    with session_scope(engine) as s:
        s.add(GemIssue(user_id=uid, gem_slug=slug, published_on=published_on))


def fare(engine, uid, slug, **values):
    row = {
        "origin": "JFK",
        "airport": "BOO",
        "return_airport": "SVJ",
        "currency": "USD",
        "status": "found",
        "run_date": TODAY,
        **values,
    }
    with session_scope(engine) as s:
        s.add(GemFare(user_id=uid, gem_slug=slug, **row))


def found_fare(**values) -> GemFare:
    row = {"status": "found", "price": Decimal("642"), "currency": "USD", "fits": True, "fit_month": 8}
    return GemFare(**{**row, "pto_cost": 6, **values})


def test_fit_pill_copy():
    assert fit_pill(None) == ("Checking fares…", "grey")
    assert fit_pill(found_fare()) == ("Fits your August range · 6 PTO", "green")
    assert fit_pill(found_fare(fits=False, fit_month=None)) == ("outside your dates", "orange")
    assert fit_pill(GemFare(status="none")) == ("No fares found lately", "grey")
    assert fit_pill(GemFare(status="failed")) == ("Checking fares…", "grey")


def test_gems_need_sign_in(client):
    for path in ("/gems", "/gems/hoegvik-islands"):
        r = client.get(path)
        assert (r.status_code, r.headers["location"]) == (303, "/")
    r = client.post("/gems/hoegvik-islands/track", headers=JSON)
    assert r.status_code == 401
    assert client.post("/gems/hoegvik-islands/track").headers["location"] == "/"


def test_gems_page_with_no_issues_says_the_first_is_coming(
    client, emailer, clean_engine, monkeypatch, tmp_path
):
    signed_in(client, emailer, clean_engine)
    monkeypatch.setenv(gems.GEMS_DIR_ENV, str(tmp_path))  # an empty catalogue: nothing to publish
    r = client.get("/gems")
    assert r.status_code == 200
    assert "The first issue is on its way." in r.text
    assert "For you: everything" in r.text and 'href="/profile#travel-style"' in r.text


def test_first_visit_publishes_and_shows_the_feature(client, emailer, clean_engine):
    uid = signed_in(client, emailer, clean_engine)
    r = client.get("/gems")
    assert r.status_code == 200
    with session_scope(clean_engine) as s:
        issued = s.scalars(select(GemIssue.gem_slug).where(GemIssue.user_id == uid)).all()
    assert issued == ["lipnica-valley"]  # no styles: catalogue order
    page = r.text
    assert "Lipnica Valley" in page and "New this week" in page
    assert "A slow train up a green valley" in page
    assert "How to do it on a budget" in page and "~$70/day" in page
    assert "Checking fares…" in page  # not priced yet
    assert 'href="/gems/lipnica-valley"' in page and "Read the full guide" in page
    assert "Track this place" in page
    assert "The first issue is on its way." not in page
    # A second visit publishes nothing new.
    client.get("/gems")
    with session_scope(clean_engine) as s:
        assert s.scalar(select(GemIssue.id).where(GemIssue.gem_slug == "hoegvik-islands")) is None


def test_feed_shows_styles_earlier_issues_and_fares(client, emailer, clean_engine):
    uid = signed_in(client, emailer, clean_engine)
    with session_scope(clean_engine) as s:
        s.get(User, uid).trip_styles = ["islands", "rail"]
    issue(clean_engine, uid, "lipnica-valley", TODAY - timedelta(days=9))
    issue(clean_engine, uid, "hoegvik-islands", TODAY - timedelta(days=2))
    fare(clean_engine, uid, "hoegvik-islands", status="none", run_date=TODAY - timedelta(days=4))
    fare(
        clean_engine,
        uid,
        "hoegvik-islands",
        price=Decimal("642"),
        fits=True,
        fit_month=8,
        pto_cost=6,
        depart_date=TODAY + timedelta(days=150),
        return_date=TODAY + timedelta(days=159),
    )
    fare(
        clean_engine,
        uid,
        "lipnica-valley",
        airport="LJU",
        return_airport="LJU",
        price=Decimal("590"),
        fits=False,
        depart_date=TODAY + timedelta(days=60),
        return_date=TODAY + timedelta(days=67),
    )
    page = client.get("/gems").text
    assert "For you:" in page and "🏝 Islands" in page and "🚆 Rail trips" in page
    feature, earlier = page.split("Earlier issues")
    assert "Høgvik Islands" in feature and "$642" in feature
    assert "Fits your August range · 6 PTO" in feature  # the latest fare, not the older miss
    assert "Lipnica Valley" in earlier and "$590" in earlier and "outside your dates" in earlier
    assert OWN_PHOTO in feature


def test_retired_gems_leave_the_feed_but_open_for_their_readers(
    client, emailer, clean_engine, monkeypatch, tmp_path
):
    for path in FIXTURES.glob("*.yaml"):
        shutil.copy(path, tmp_path / path.name)
    retired = tmp_path / "lipnica-valley.yaml"
    text = retired.read_text(encoding="utf-8").replace("status: approved", "status: retired")
    retired.write_text(text, encoding="utf-8")
    monkeypatch.setenv(gems.GEMS_DIR_ENV, str(tmp_path))
    uid = signed_in(client, emailer, clean_engine)
    issue(clean_engine, uid, "lipnica-valley", TODAY - timedelta(days=3))
    issue(clean_engine, uid, "hoegvik-islands", TODAY - timedelta(days=10))
    page = client.get("/gems").text
    assert "Lipnica Valley" not in page  # out of the feed, though it is their newest issue
    assert "Høgvik Islands" in page
    assert client.get("/gems/lipnica-valley").status_code == 200  # it was issued to them
    # Someone it was never issued to gets a 404.
    other = signed_in(client, emailer, clean_engine, "friend@example.com")
    assert other != uid
    assert client.get("/gems/lipnica-valley").status_code == 404


def test_drafts_are_404(client, emailer, clean_engine):
    uid = signed_in(client, emailer, clean_engine)
    issue(clean_engine, uid, "ardmore-falls")  # even if somehow issued
    assert client.get("/gems/ardmore-falls").status_code == 404
    assert client.get("/gems/no-such-place").status_code == 404
    assert client.post("/gems/ardmore-falls/track", headers=JSON).status_code == 404


def test_any_signed_in_user_can_open_an_approved_guide(client, emailer, clean_engine):
    uid = signed_in(client, emailer, clean_engine)
    r = client.get("/gems/hoegvik-islands")  # never issued to them
    assert r.status_code == 200
    page = r.text
    assert "<h1>Høgvik Islands</h1>" in page
    assert "🥾 Hiking &amp; camping" in page and "🏝 Islands" in page and "Jun–Aug" in page
    assert "<h2>Getting there</h2>" in page and "<strong>Bodø</strong>" in page
    assert "<li>Camp on open land away from houses</li>" in page
    assert "How to do it on a budget" in page and "Free wild camping" in page and "~$45/day" in page
    assert OWN_PHOTO in page and "Example Photographer" in page  # its own photo and credit
    assert "Checking fares…" in page
    with session_scope(clean_engine) as s:  # viewing doesn't add it to their issues
        assert s.scalar(select(GemIssue.id).where(GemIssue.user_id == uid)) is None


def test_the_gems_own_photo_wins_and_a_found_one_fills_in(client, emailer, clean_engine):
    signed_in(client, emailer, clean_engine)
    with session_scope(clean_engine) as s:
        found = (("gem-hoegvik-islands", "found_coast.jpg"), ("gem-lipnica-valley", "found_valley.jpg"))
        for code, url in found:
            s.add(
                PlacePhotoRow(
                    code=code,
                    image_url=f"https://upload.wikimedia.org/{url}",
                    width=1280,
                    height=850,
                    author="Commons Contributor",
                    licence="CC BY 4.0",
                    source_url=f"https://commons.wikimedia.org/wiki/File:{url}",
                    status="ok",
                    fetched_at=datetime.now(UTC),
                )
            )
    hoegvik = client.get("/gems/hoegvik-islands").text
    assert OWN_PHOTO in hoegvik and "found_coast.jpg" not in hoegvik
    lipnica = client.get("/gems/lipnica-valley").text
    assert "found_valley.jpg" in lipnica and "Commons Contributor" in lipnica


def test_guide_lists_facts_with_sources(client, emailer, clean_engine):
    signed_in(client, emailer, clean_engine)
    page = client.get("/gems/hoegvik-islands").text
    assert "Facts we checked" in page
    facts = page.split("Facts we checked")[1]
    assert "Wild camping is allowed on uncultivated land away from houses." in facts
    assert 'href="https://example.org/hoegvik/camping"' in facts
    assert 'href="https://example.org/hoegvik/ferry"' in facts


def test_guide_shows_the_persons_fare(client, emailer, clean_engine):
    uid = signed_in(client, emailer, clean_engine)
    fare(
        clean_engine,
        uid,
        "hoegvik-islands",
        price=Decimal("642"),
        fits=False,
        depart_date=TODAY + timedelta(days=30),
        return_date=TODAY + timedelta(days=39),
        deep_link="https://www.google.com/travel/flights?x=1",
    )
    page = client.get("/gems/hoegvik-islands").text
    assert "$642" in page and "outside your dates" in page and "JFK" in page
    assert 'href="https://www.google.com/travel/flights?x=1"' in page
    fare(clean_engine, uid, "hoegvik-islands", status="none")
    assert "No fares found lately" in client.get("/gems/hoegvik-islands").text


def test_track_adds_the_destination_in_place(make_client, emailer, clean_engine):  # noqa: F811
    c = make_client()
    uid = signed_in(c, emailer, clean_engine)
    with session_scope(clean_engine) as s:
        s.get(User, uid).ideal_trip_days = 9
    r = c.post("/gems/hoegvik-islands/track", headers=JSON)
    assert r.status_code == 200 and r.json()["ok"]
    tracker_id = r.json()["tracker_id"]
    with session_scope(clean_engine) as s:
        tracker = s.get(Tracker, tracker_id)
        assert tracker.user_id == uid and tracker.active and tracker.target_days == 9
        from ptopilot.data import load_geo

        dest = load_geo(clean_engine).destination(tracker.destination_code)
        assert list(dest.airports) == ["BOO"] and not dest.return_airports  # round trip on the arrival
    # Without JS: a redirect to the destination page; tracking again keeps the one tracker.
    with session_scope(clean_engine) as s:
        s.get(User, uid).ideal_trip_days = None
    r = c.post("/gems/hoegvik-islands/track")
    assert (r.status_code, r.headers["location"]) == (303, f"/trackers/{tracker_id}")
    with session_scope(clean_engine) as s:
        assert s.get(Tracker, tracker_id).target_days == 10  # no ideal length: 10


def test_track_button_reads_tracking_when_already_tracked(make_client, emailer, clean_engine):  # noqa: F811
    c = make_client()
    uid = signed_in(c, emailer, clean_engine)
    page = c.get("/gems/hoegvik-islands").text
    assert "Track this place" in page and 'action="/gems/hoegvik-islands/track"' in page
    assert "data-inplace" in page
    tracker_id = c.post("/gems/hoegvik-islands/track", headers=JSON).json()["tracker_id"]
    page = c.get("/gems/hoegvik-islands").text
    assert "Track this place" not in page
    assert "Tracking" in page and f'href="/trackers/{tracker_id}"' in page
    issue(clean_engine, uid, "hoegvik-islands")
    feed = c.get("/gems").text
    assert "Tracking" in feed and f'href="/trackers/{tracker_id}"' in feed


def test_nav_links_hidden_gems(client, emailer, clean_engine):
    signed_in(client, emailer, clean_engine)
    page = client.get("/gems").text
    assert re.search(r'<a href="/gems"\s*aria-current="page">Hidden gems</a>', page)
    assert re.search(r'<a href="/gems"\s*>Hidden gems</a>', client.get("/profile").text)


def test_dashboard_shows_this_weeks_gem(client, emailer, clean_engine):
    uid = signed_in(client, emailer, clean_engine)
    assert "This week's hidden gem" not in client.get("/").text  # no issue yet; the dashboard publishes none
    issue(clean_engine, uid, "hoegvik-islands")
    page = client.get("/").text
    assert "This week's hidden gem" in page
    card = page.split("This week's hidden gem")[1]
    assert "Høgvik Islands" in card and 'href="/gems"' in card
    assert page.index('id="cards"') < page.index("This week's hidden gem")  # under the destination cards


def test_a_failed_check_keeps_the_known_fare(client, emailer, clean_engine):
    uid = signed_in(client, emailer, clean_engine)
    fare(
        clean_engine,
        uid,
        "hoegvik-islands",
        price=Decimal("642"),
        fits=True,
        fit_month=8,
        pto_cost=6,
        depart_date=TODAY + timedelta(days=150),
        return_date=TODAY + timedelta(days=159),
        run_date=TODAY - timedelta(days=3),
    )
    fare(clean_engine, uid, "hoegvik-islands", status="failed")  # a newer, transient failure
    page = client.get("/gems/hoegvik-islands").text
    assert "$642" in page and "Fits your August range · 6 PTO" in page
    assert "Checking fares…" not in page


def test_only_failed_checks_read_checking(client, emailer, clean_engine):
    uid = signed_in(client, emailer, clean_engine)
    fare(clean_engine, uid, "hoegvik-islands", status="failed")
    assert "Checking fares…" in client.get("/gems/hoegvik-islands").text
