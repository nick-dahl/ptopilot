from datetime import date

from ptopilot.data import load_geo, load_seasons
from ptopilot.digest.render import render
from ptopilot.digest.select import build_digests
from tests.digest.conftest import RUN, add_candidate, add_tracker, add_user

GEO, SEASONS = load_geo(), load_seasons()


def digest(engine):
    [d] = build_digests(engine, GEO, SEASONS, RUN)
    return d


def test_digest_marks_standout_deals_and_leads_with_one(clean_engine):
    uid = add_user(clean_engine)
    t1 = add_tracker(clean_engine, uid)
    t2 = add_tracker(clean_engine, uid, code="CAMINO_PORTUGUES")
    add_candidate(clean_engine, t1, 600, level="great", go_now=95, expected_days=6)  # best score, ordinary
    add_candidate(
        clean_engine,
        t2,
        700,
        level="great",
        go_now=88,
        expected_days=2,
        dest="OPO",
        depart=date(2027, 4, 2),
        ret=date(2027, 4, 11),
    )
    d = digest(clean_engine)
    assert d.deals[0].standout and d.deals[0].destination.startswith("Camino")
    assert d.deals[0].expected_days == 2 and not d.deals[1].standout
    _, html, text = render(d)
    assert html.count("Rare: likely gone within ~2 days") == 1
    assert text.count("Rare: likely gone within ~2 days") == 1
    assert "likely gone within ~6 days" in html


def test_ordinary_deals_get_the_duration_line_but_no_standout_look(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 600, level="great", go_now=95, expected_days=6)
    _, html, text = render(digest(clean_engine))
    assert "likely gone within ~6 days" in html and "likely gone within ~6 days" in text
    assert "Rare:" not in html and "Rare:" not in text and "f59e0b" not in html


def test_unknown_duration_shows_no_line(clean_engine):
    t = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, t, 600, level="great", go_now=95)
    _, html, text = render(digest(clean_engine))
    assert "likely" not in html and "not enough history" not in html + text
