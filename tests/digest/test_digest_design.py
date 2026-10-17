"""The V2 digest: a lead deal card, compact rows for the rest, and email-safe structure."""

from datetime import timedelta

from ptopilot.core.geo import Palette
from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import DigestSend
from ptopilot.db.session import session_scope
from ptopilot.digest.render import bar_cells, render
from ptopilot.digest.select import Digest, build_digests
from ptopilot.web.viz import BarGeometry
from tests.digest.conftest import RUN, add_baseline, add_candidate, add_tracker, add_user
from tests.digest.test_render import NOW, ROW, card

TEAL = Palette("#0e7490", "#c3dde3")
GREEN = Palette("#15803d", "#c5dfcf")


def two_deals(**digest_fields) -> Digest:
    lead = card(palette=TEAL, sigma=50.0, typical=700)
    other = card(candidate_id=2, tracker_id=2, destination="Madeira", palette=GREEN, price=828, go_now=60)
    return Digest(1, "nick@example.com", RUN, [lead, other], [ROW], **digest_fields)


def test_lead_deal_gets_the_full_card_in_its_color():
    _, html, _ = render(two_deals(), now=NOW)
    assert "Best this week" in html and "background:#0e7490" in html
    assert html.count("View flights") == 1  # only the lead card has the button


def test_lead_card_draws_the_price_bar_from_table_cells():
    _, html, _ = render(two_deals(), now=NOW)
    assert 'bgcolor="#c3dde3"' in html and 'bgcolor="#0e7490"' in html


def test_other_deals_are_compact_rows_linking_to_the_site_when_it_is_configured():
    _, html, _ = render(two_deals(), now=NOW, base_url="https://ptopilot.example")
    assert 'href="https://ptopilot.example/trackers/2"' in html and "Madeira" in html and "$828" in html
    _, html, _ = render(two_deals(), now=NOW)
    assert "/trackers/2" not in html and 'href="https://www.google.com/travel/flights' in html


def test_preheader_and_outlook_wrapper():
    _, html, _ = render(two_deals(), now=NOW)
    assert "Azores $603 (14% below typical) + 1 more" in html.split("<table")[0]  # hidden, before the layout
    assert "<!--[if mso]>" in html and 'width="600"' in html


def test_quiet_digest_wording_depends_on_whether_deals_went_out_before():
    _, html, text = render(Digest(1, "nick@example.com", RUN, [], [ROW], held_back=2), now=NOW)
    assert "No new deals since your last digest" in html and "No new deals since your last digest" in text
    _, html, _ = render(Digest(1, "nick@example.com", RUN, [], [ROW]), now=NOW)
    assert "Nothing below typical yet" in html


def test_text_version_keeps_the_same_order():
    _, _, text = render(two_deals(), now=NOW)
    assert text.index("Azores") < text.index("Madeira") < text.index("Your trackers")


def test_bar_cells_cover_the_track_once():
    cells = bar_cells(BarGeometry(dot=24.0, band_start=33.3, band_end=66.7))
    assert [kind for _, kind in cells] == ["track", "dot", "track", "band", "track"]
    assert abs(sum(width for width, _ in cells) - 100) < 0.5
    inside = bar_cells(BarGeometry(dot=50.0, band_start=33.3, band_end=66.7))
    assert [kind for _, kind in inside] == ["track", "band", "dot", "band", "track"]


def test_selection_counts_deals_held_back_as_already_sent(clean_engine):
    uid = add_user(clean_engine)
    t = add_tracker(clean_engine, uid)
    old = add_candidate(clean_engine, t, 600, run_date=RUN - timedelta(days=3))
    with session_scope(clean_engine) as s:
        item = {
            "candidate_id": old,
            "tracker_id": t,
            "route_query_id": 1,
            "evening_departure": True,
            "price": 600,
        }
        s.add(DigestSend(user_id=uid, items=[item]))
    add_candidate(clean_engine, t, 590, run_date=RUN)
    (d,) = build_digests(clean_engine, load_geo(), load_seasons(), RUN)
    assert d.deals == [] and d.held_back == 1


def test_selection_gives_cards_their_destination_palette_and_spread(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 603)
    add_baseline(clean_engine, 700)
    (d,) = build_digests(clean_engine, load_geo(), load_seasons(), RUN)
    assert d.deals[0].palette.color == "#0e7490" and d.deals[0].sigma == 50.0
    assert d.trackers[0].palette.color == "#0e7490"
