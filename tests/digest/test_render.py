from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from ptopilot.digest.render import banner_text, checked_ago, clock, duration, money, render, subject
from ptopilot.digest.select import DealCard, Digest, TrackerRow
from ptopilot.plan_totals import YearTotals

NOW = datetime(2027, 3, 4, 12, 0, tzinfo=UTC)


def card(**overrides) -> DealCard:
    fields = dict(
        candidate_id=1,
        tracker_id=1,
        route_query_id=1,
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
        "departs 10:00pm", "TP 202", "(outbound flight)", "checked 9 hours ago", "View flights",
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


def test_snooze_links_appear_under_each_card_when_provided():
    def links(c):
        return [("Not this trip", f"https://app.example/s/tok{c.candidate_id}")]

    _, html, text = render(digest(card()), now=NOW, links=links)
    assert 'href="https://app.example/s/tok1"' in html and "Not this trip" in html
    assert "Not this trip: https://app.example/s/tok1" in text
    _, html, _ = render(digest(card()), now=NOW)
    assert "/s/" not in html


def test_fit_notes_render_in_html_and_text_on_every_card():
    notes = ("Overlaps your booked Madeira trip.", "Doesn't fit your remaining PTO (2 left).")
    d = digest(card(fit_notes=notes), card(candidate_id=2, destination="Lisbon", fit_notes=notes[:1]))
    _, html, text = render(d, NOW)
    assert html.count("Overlaps your booked Madeira trip.") == 2
    assert "remaining PTO (2 left)." in html
    assert text.count("Note: Overlaps your booked Madeira trip.") == 2
    assert "Note: Doesn't fit your remaining PTO (2 left)." in text
    assert "Note:" not in render(digest(card()), NOW)[2]


def test_banner_text_left_and_over():
    assert banner_text(YearTotals(2027, 25, 1, 5, 15)) == "2027: 5 booked · 15 planned · 4 PTO left"
    assert banner_text(YearTotals(2027, 25, 0, 5, 15)) == "2027: 5 booked · 15 planned · 5 PTO left"
    assert banner_text(YearTotals(2027, 24, 0, 5, 24)) == "2027: 5 booked · 24 planned · 5 PTO over"


def test_banner_renders_in_html_and_text():
    banner = YearTotals(2027, 25, 1, 5, 15)
    d = digest(card())
    d.banner = banner
    _, html, text = render(d, NOW)
    line = "2027: 5 booked · 15 planned · 4 PTO left"
    assert line in html and html.index(line) < html.index("Best this week")
    assert text.splitlines()[0] == line
    quiet = Digest(1, "nick@example.com", date(2027, 3, 4), [], [ROW], banner=banner)
    assert line in render(quiet, NOW)[1]
    _, html, text = render(digest(card()), NOW)
    assert "booked ·" not in html and "booked ·" not in text


def test_text_notes_start_on_their_own_line():
    notes = ("Overlaps your booked Madeira trip.",)
    text = render(digest(card(fit_notes=notes), card(candidate_id=2, fit_notes=notes)), NOW)[2]
    assert all(line.strip().startswith("Note:") for line in text.splitlines() if "Note:" in line)


def test_forgiven_note_renders_in_html_and_text_email():
    note = "6h layover in Madrid (worth it at 45% below typical)"
    d = digest(card(misery_note=note), card(candidate_id=2, destination="Lisbon", misery_note=note))
    _, html, text = render(d, NOW)
    assert html.count(note) == 2
    assert text.count(f"Note: {note}") == 2
    assert "layover" not in render(digest(card()), NOW)[1]
