from datetime import date, timedelta
from decimal import Decimal

from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import RelatedCheck, RelatedLink, Tracker
from ptopilot.db.session import session_scope
from ptopilot.digest.render import render, subject
from ptopilot.digest.select import build_digests
from tests.digest.conftest import RUN, add_candidate, add_tracker, add_user

GEO, SEASONS = load_geo(), load_seasons()
MAIN, PLACE = GEO.destination("AZORES").name, GEO.destination("MADEIRA").name


def digest(engine):
    [d] = build_digests(engine, GEO, SEASONS, RUN)
    return d


def add_check(
    engine, user_id, tracker_id, live=640, typical=1000, confirmed=True, run_date=RUN, airport="FNC"
):
    with session_scope(engine) as s:
        link = RelatedLink(
            user_id=user_id, tracker_id=tracker_id, airport=airport, place_code="MADEIRA", status="accepted"
        )
        s.add(link)
        s.flush()
        s.add(
            RelatedCheck(
                run_date=run_date,
                user_id=user_id,
                tracker_id=tracker_id,
                link_id=link.id,
                origin="JFK",
                airport=airport,
                depart_date=date(2027, 6, 5),
                return_date=date(2027, 6, 12),
                cached_price=Decimal(live),
                typical_median=Decimal(typical),
                live_price=Decimal(live) if confirmed else None,
                currency="USD",
                pto_cost=5,
                deep_link="https://www.google.com/travel/flights/search?tfs=R",
                confirmed=confirmed,
            )
        )


def setup(engine):
    uid = add_user(engine)
    tid = add_tracker(engine, uid)
    add_candidate(engine, tid, 900, level="none", go_now=0)  # a scan ran, but nothing worth a deal
    return uid, tid


def test_digest_has_an_also_worth_a_look_section(clean_engine):
    uid, tid = setup(clean_engine)
    add_check(clean_engine, uid, tid)
    d = digest(clean_engine)
    [card] = d.related
    assert (card.place, card.instead_of, card.pct_below) == (PLACE, MAIN, 36)
    _, html, text = render(d)
    for body in (html, text):
        assert "Also worth a look" in body
        assert f"{PLACE} instead of {MAIN}" in body
        assert f"36% below {MAIN}'s typical" in body
        assert "$640" in body and "https://www.google.com/travel/flights" in body
    assert html.index("Also worth a look") < html.index("Your trackers")


def test_at_most_three_related_cards_biggest_discount_first(clean_engine):
    uid, tid = setup(clean_engine)
    for i, live in enumerate([700, 500, 800, 600, 650]):
        add_check(clean_engine, uid, tid, live=live, airport=f"F{i}X")
    assert [c.pct_below for c in digest(clean_engine).related] == [50, 40, 35]


def test_unconfirmed_or_old_checks_are_not_shown(clean_engine):
    uid, tid = setup(clean_engine)
    add_check(clean_engine, uid, tid, confirmed=False)
    add_check(clean_engine, uid, tid, run_date=RUN - timedelta(days=1), airport="XXA")
    d = digest(clean_engine)
    assert d.related == []
    _, html, text = render(d)
    assert "Also worth a look" not in html + text


def test_a_digest_with_only_related_deals_is_not_quiet(clean_engine):
    uid, tid = setup(clean_engine)
    assert digest(clean_engine).quiet
    add_check(clean_engine, uid, tid)
    d = digest(clean_engine)
    assert not d.deals and not d.quiet
    sub, html, text = render(d)
    assert sub == f"ptopilot: {PLACE} instead of {MAIN} $640"
    assert "quiet week" not in html + text and subject(d) == sub


def test_related_cards_never_get_the_standout_look(clean_engine):
    uid, tid = setup(clean_engine)
    add_check(clean_engine, uid, tid, live=300)
    _, html, text = render(digest(clean_engine))
    assert "Rare" not in html + text and "f59e0b" not in html


def test_a_snoozed_tracker_gets_no_related_cards_and_stays_quiet(clean_engine):
    uid, tid = setup(clean_engine)
    add_check(clean_engine, uid, tid)
    with session_scope(clean_engine) as s:
        s.get(Tracker, tid).snoozed_until = RUN
    d = digest(clean_engine)
    assert d.related == [] and d.quiet
    with session_scope(clean_engine) as s:
        s.get(Tracker, tid).snoozed_until = RUN - timedelta(days=1)  # snooze over: back again
    assert len(digest(clean_engine).related) == 1
