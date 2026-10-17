from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from ptopilot.digest.render import checked_ago, clock, duration, money, render, subject
from ptopilot.digest.select import DealCard, Digest, TrackerRow

NOW = datetime(2027, 3, 4, 12, 0, tzinfo=UTC)


def card(**overrides) -> DealCard:
    fields = dict(
        candidate_id=1,
        tracker_id=1,
        destination="Azores",
        origin="JFK",
        dest_airport="PDL",
        return_airport="PDL",
        depart_date=date(2027, 3, 5),
        return_date=date(2027, 3, 14),
        evening_departure=True,
        price=Decimal(603),
        currency="USD",
        typical=Decimal(870),
        deal_level="great",
        go_now=84,
        confidence="normal",
        verified=True,
        pto_cost=5,
        days_away=10,
        days_off=(),
        season_rating="shoulder",
        weather_note="Mild (~16°C) but rainy",
        carrier="Tap Air Portugal",
        stops=1,
        duration_min=600,
        outbound_departure=datetime(2027, 3, 5, 22, 0),
        flight_numbers=("TP 202",),
        deep_link="https://www.google.com/travel/flights/search?tfs=X&curr=USD",
        observed_at=NOW - timedelta(hours=9),
    )  # noqa: C408
    return DealCard(**(fields | overrides))


ROW = TrackerRow(1, "Azores", Decimal(603), Decimal(870), "down", "May", None)


def digest(*deals) -> Digest:
    return Digest(1, "nick@example.com", date(2027, 3, 4), list(deals), [ROW])


def test_helpers():
    assert money(Decimal("1239.4")) == "$1,239"
    assert money(None) == "—"
    assert duration(1195) == "19h 55m"
    assert clock(datetime(2027, 3, 5, 18, 25)) == "6:25pm" and clock(datetime(2027, 3, 5, 0, 5)) == "12:05am"
    assert checked_ago(NOW - timedelta(minutes=10), NOW) == "checked under an hour ago"
    assert checked_ago(NOW - timedelta(hours=9), NOW) == "checked 9 hours ago"
    assert checked_ago(NOW - timedelta(days=3), NOW) == "checked 3 days ago"


def test_subject_leads_with_the_top_deal():
    assert (
        subject(digest(card(), card(candidate_id=2))) == "ptopilot: Azores $603 (31% below typical) + 1 more"
    )
    assert subject(digest()) == "ptopilot: a quiet week for your trips"


def test_html_card_contents():
    _, html, _ = render(digest(card(days_off=("Memorial Day",))), now=NOW)
    for fragment in (
        "Azores", "Great deal", "Go-now 84", "Fri Mar 5 → Sun Mar 14", "leave after work", "$603", "~$870",
        "31% below", "5 PTO days", "Memorial Day gives you a free day", "1 stop", "10h 00m out",
        "departs 10:00pm", "TP 202", "(outbound flight)", "checked 9 hours ago", "See flights",
        "tfs=X&amp;curr=USD", "Your trackers", "↓",
    ):  # fmt: skip
        assert fragment in html, fragment


def test_open_jaw_and_low_confidence_wording():
    _, html, text = render(
        digest(card(dest_airport="OPO", return_airport="SCQ", confidence="low", verified=False)), now=NOW
    )
    assert "JFK → OPO, home from SCQ" in html and "both flights" in html
    assert "Cached price, not yet confirmed live" in html and "still being learned" in html
    assert "JFK -> OPO, home from SCQ" in text and "both flights" in text


def test_html_escapes_but_text_does_not():
    _, html, text = render(digest(card(carrier="Trains & <Planes>")), now=NOW)
    assert "Trains &amp; &lt;Planes&gt;" in html
    assert "Trains & <Planes>" in text
    assert "&amp;" not in text


def test_quiet_digest_still_shows_trackers():
    subj, html, text = render(digest(), now=NOW)
    assert "A quiet week" in html and "Your trackers" in html
    assert "Azores: best $603, typical $870" in text
