"""Stage `alerts`: rare, short-lived offers are emailed right away, after checking the flight home."""

import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

from ptopilot import config
from ptopilot.db.models import AlertSend, Candidate, LiveCheck, RouteQuery, ShortlistEntry, SourceBudget
from ptopilot.db.session import session_scope
from ptopilot.digest.render import render_alert
from ptopilot.digest.select import build_digests
from ptopilot.notify.email import EmailError
from ptopilot.pipeline import alerts, expand, live_verify, runner, shortlist
from tests.digest.conftest import RUN, add_baseline, add_candidate, add_tracker, add_user
from tests.pipeline.conftest import GEO, SEASONS, FakeLiveSource, answering, option
from tests.pipeline.conftest import add_tracker as add_pipeline_tracker
from tests.pipeline.conftest import add_user as add_pipeline_user

SUBJECT = "Rare: Azores $520 (31% below typical) — likely gone within ~2 days"


class CapturingEmailer:
    def __init__(self, fail_for=()):
        self.sent: list[tuple[str, str, str, str]] = []
        self.fail_for = set(fail_for)

    def send(self, to, subject, html, text):
        if to in self.fail_for:
            raise EmailError(f"resend: HTTP 422: bad recipient {to}")
        self.sent.append((to, subject, html, text))
        return "id"


def standout(engine, tracker_id, price=520, go_now=90, expected_days=2, **fields) -> int:
    return add_candidate(
        engine, tracker_id, price, level="great", go_now=go_now, expected_days=expected_days, **fields
    )


def alert_ctx(make_ctx, **fields):
    return make_ctx(**({"run_date": RUN, "emailer": CapturingEmailer()} | fields))


def alert_rows(engine):
    with session_scope(engine) as s:
        return [(a.user_id, a.tracker_id, a.candidate_id, a.run_date) for a in s.scalars(select(AlertSend))]


def return_rows(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(LiveCheck).where(LiveCheck.purpose == "return")))


def azores(engine, email="nick@example.com"):
    uid = add_user(engine, email)
    tid = add_tracker(engine, uid)
    add_baseline(engine, 750)
    return uid, tid


def test_a_standout_offer_is_emailed_right_away(make_ctx):
    ctx = alert_ctx(make_ctx)
    uid, tid = azores(ctx.engine)
    cid = standout(ctx.engine, tid)
    counts = alerts.run(ctx)
    [(to, subject, html, text)] = ctx.emailer.sent
    assert to == "nick@example.com" and subject == SUBJECT
    assert alert_rows(ctx.engine) == [(uid, tid, cid, RUN)]
    assert counts["standout"] == 1 and counts["sent"] == 1
    assert "View flights" in html and "Go-now 90" in html and "likely gone within ~2 days" in text


def test_the_alert_carries_snooze_links_when_the_web_app_is_configured(make_ctx):
    ctx = alert_ctx(make_ctx, app_base_url="https://ptopilot.example", secret_key="test-secret")
    _, tid = azores(ctx.engine)
    standout(ctx.engine, tid)
    alerts.run(ctx)
    [(_, _, html, text)] = ctx.emailer.sent
    assert "https://ptopilot.example/s/" in html and "https://ptopilot.example/s/" in text


def test_render_alert_uses_the_digest_look(clean_engine):
    _, tid = azores(clean_engine)
    standout(clean_engine, tid)
    [digest] = build_digests(clean_engine, GEO, SEASONS, RUN, min_level="great", skip_sent=False)
    subject, html, text = render_alert(digest.deals[0], None)
    assert subject == SUBJECT
    assert "fonts.googleapis" not in html and "<link" not in html and 'style="' in html
    assert "Rare: likely gone within ~2 days" in html and "$520" in text and "~$750" in text


def test_one_alert_a_day_picks_the_best(make_ctx):
    ctx = alert_ctx(make_ctx)
    uid, tid = azores(ctx.engine)
    t2 = add_tracker(ctx.engine, uid, code="MADEIRA")
    add_baseline(ctx.engine, 750, dest="FNC")
    standout(ctx.engine, tid, go_now=88)
    best = standout(ctx.engine, t2, go_now=95, dest="FNC")
    counts = alerts.run(ctx)
    [(_, subject, _, _)] = ctx.emailer.sent
    assert subject.startswith("Rare: Madeira")
    assert [r[2] for r in alert_rows(ctx.engine)] == [best]
    assert counts["held_daily_cap"] == 1 and counts["sent"] == 1


def test_same_destination_waits_a_week(make_ctx):
    for days_ago, sent in ((5, 0), (7, 1)):
        ctx = alert_ctx(make_ctx)
        with ctx.engine.begin() as conn:
            conn.exec_driver_sql("TRUNCATE users, route_queries, route_baselines RESTART IDENTITY CASCADE")
        uid, tid = azores(ctx.engine)
        with session_scope(ctx.engine) as s:
            s.add(AlertSend(user_id=uid, tracker_id=tid, run_date=RUN - timedelta(days=days_ago)))
        standout(ctx.engine, tid)
        counts = alerts.run(ctx)
        assert len(ctx.emailer.sent) == sent, days_ago
        assert counts["held_same_destination"] == 1 - sent


def test_a_rerun_does_not_resend(make_ctx):
    ctx = alert_ctx(make_ctx)
    _, tid = azores(ctx.engine)
    standout(ctx.engine, tid)
    alerts.run(ctx)
    counts = alerts.run(ctx)
    assert len(ctx.emailer.sent) == 1 and len(alert_rows(ctx.engine)) == 1
    assert counts["sent"] == 0 and counts["held_daily_cap"] == 1


def test_ordinary_great_deals_are_not_alerted(make_ctx):
    ctx = alert_ctx(make_ctx)
    uid, tid = azores(ctx.engine)
    standout(ctx.engine, tid, go_now=80)
    standout(ctx.engine, tid, expected_days=5, depart=RUN + timedelta(days=2), ret=RUN + timedelta(days=11))
    counts = alerts.run(ctx)
    assert ctx.emailer.sent == [] and alert_rows(ctx.engine) == []
    assert counts["standout"] == 0


def test_only_todays_run_and_active_trackers_are_alerted(make_ctx):
    ctx = alert_ctx(make_ctx)
    _, tid = azores(ctx.engine)
    standout(ctx.engine, tid, run_date=RUN - timedelta(days=1))  # yesterday's scan
    other = add_tracker(ctx.engine, add_user(ctx.engine, "other@example.com"), active=False)
    standout(ctx.engine, other)
    alerts.run(ctx)
    assert ctx.emailer.sent == []


def test_dry_run_sends_nothing(make_ctx):
    ctx = alert_ctx(make_ctx, dry_run=True)
    _, tid = azores(ctx.engine)
    standout(ctx.engine, tid)
    counts = alerts.run(ctx)
    assert counts["would_send"] == 1 and counts.get("sent", 0) == 0
    assert ctx.emailer.sent == [] and alert_rows(ctx.engine) == []


def test_alerted_offers_still_appear_in_the_next_digest(make_ctx):
    ctx = alert_ctx(make_ctx)
    _, tid = azores(ctx.engine)
    cid = standout(ctx.engine, tid)
    alerts.run(ctx)
    [digest] = build_digests(ctx.engine, GEO, SEASONS, RUN)
    assert [d.candidate_id for d in digest.deals] == [cid] and digest.held_back == 0
    with session_scope(ctx.engine) as s:
        assert s.get(Candidate, cid).state != "sent"


def test_alerts_stage_runs_last():
    assert list(runner.STAGES)[-1] == "alerts"
    assert "alerts" in runner.CONTINUE_ON_FAILURE


def test_a_failed_email_does_not_stop_the_others_and_logs_no_address(make_ctx, caplog):
    ctx = alert_ctx(make_ctx, emailer=CapturingEmailer(fail_for={"nick@example.com"}))
    _, tid = azores(ctx.engine)
    standout(ctx.engine, tid)
    t2 = add_tracker(ctx.engine, add_user(ctx.engine, "other@example.com"))
    standout(ctx.engine, t2)
    with caplog.at_level(logging.INFO):
        counts = alerts.run(ctx)
    assert [to for to, *_ in ctx.emailer.sent] == ["other@example.com"]
    assert counts["failed"] == 1 and counts["sent"] == 1 and len(alert_rows(ctx.engine)) == 1
    assert "@example.com" not in caplog.text


def two_returns(ctx):
    """Two Azores standouts: the better one comes home Mar 14, the next one Mar 21."""
    uid, tid = azores(ctx.engine)
    best = standout(ctx.engine, tid, go_now=95)
    nxt = standout(ctx.engine, tid, go_now=90, depart=RUN + timedelta(days=8), ret=RUN + timedelta(days=17))
    return uid, tid, best, nxt


def test_a_failed_return_tries_the_next_standout(make_ctx, monkeypatch):
    ctx = alert_ctx(make_ctx)
    _, _, best, nxt = two_returns(ctx)
    seen = []

    def fake(sources, **kw):
        seen.append(kw)
        return (
            ("fail", "a 14-hour layover in Toronto")
            if kw["depart"] == RUN + timedelta(days=10)
            else ("pass", None)
        )

    monkeypatch.setattr(alerts, "check_return", fake)
    counts = alerts.run(ctx)
    assert len(ctx.emailer.sent) == 1 and [r[2] for r in alert_rows(ctx.engine)] == [nxt]
    assert counts["return_checks"] == 2 and counts["return_failed"] == 1
    first = seen[0]
    assert (first["home"], first["from_airport"]) == ("JFK", "PDL")
    assert first["price"] == 520.0 and first["typical_median"] == 750.0 and first["confident"] is True
    assert first["destination"].code == "AZORES"


def test_an_unknown_return_still_sends(make_ctx, monkeypatch):
    ctx = alert_ctx(make_ctx)
    _, tid = azores(ctx.engine)
    standout(ctx.engine, tid)
    monkeypatch.setattr(alerts, "check_return", lambda sources, **kw: ("unknown", None))
    counts = alerts.run(ctx)
    assert len(ctx.emailer.sent) == 1 and counts["return_checks"] == 1


def test_return_checks_are_capped(make_ctx, monkeypatch):
    ctx = alert_ctx(make_ctx)
    _, tid = azores(ctx.engine)
    for i in range(4):
        standout(ctx.engine, tid, depart=RUN + timedelta(days=1 + i), ret=RUN + timedelta(days=10 + i))
    calls = []
    monkeypatch.setattr(alerts, "check_return", lambda sources, **kw: calls.append(kw) or ("fail", "no"))
    counts = alerts.run(ctx)
    assert len(calls) == config.RETURN_CHECKS_PER_DAY == counts["return_checks"]
    assert ctx.emailer.sent == [] and alert_rows(ctx.engine) == []
    assert counts["held_return_check_cap"] == 1


def test_dry_run_lists_return_verdicts(make_ctx, monkeypatch, caplog):
    ctx = alert_ctx(make_ctx, dry_run=True)
    two_returns(ctx)

    def fake(sources, **kw):
        return ("fail", "a long layover") if kw["depart"] == RUN + timedelta(days=10) else ("unknown", None)

    monkeypatch.setattr(alerts, "check_return", fake)
    with caplog.at_level(logging.INFO, logger="ptopilot.pipeline.alerts"):
        counts = alerts.run(ctx)
    assert counts["would_send_return_fail"] == 1 and counts["would_send_return_unknown"] == 1
    assert counts.get("would_send_return_pass", 0) == 0 and counts["would_send"] == 1
    assert sum("return" in r.getMessage() for r in caplog.records) == 2
    assert ctx.emailer.sent == [] and alert_rows(ctx.engine) == []


# --- the real return search: sources, budget and LiveCheck bookkeeping ---


def test_return_searches_are_recorded_and_charged(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 8, "per_month": 250})
    google = FakeLiveSource("google_flights", answering())  # no options: falls through to SerpApi
    serp = FakeLiveSource("serpapi", answering(option(300, stops=0, duration=330), source="serpapi"))
    ctx = alert_ctx(make_ctx, live_sources=[google, serp])
    _, tid = azores(ctx.engine)
    cid = standout(ctx.engine, tid)
    counts = alerts.run(ctx)
    assert len(ctx.emailer.sent) == 1 and counts["return_checks"] == 1
    [q] = google.calls
    assert (q.origin, q.dest_airport, q.depart_date, q.one_way) == (
        "PDL",
        "JFK",
        RUN + timedelta(days=10),
        True,
    )
    rows = return_rows(ctx.engine)
    assert sorted((r.source, r.ok) for r in rows) == [("google_flights", True), ("serpapi", True)]
    with session_scope(ctx.engine) as s:
        rq_id = s.get(Candidate, cid).route_query_id
        assert {r.route_query_id for r in rows} == {rq_id}
        assert s.scalar(select(SourceBudget.calls_used).filter_by(source="serpapi")) == 1


def test_serpapi_is_left_out_when_its_budget_is_spent(make_ctx, monkeypatch):
    monkeypatch.setitem(config.SOURCE_BUDGETS, "serpapi", {"per_day": 0, "per_month": 250})
    google = FakeLiveSource("google_flights", answering())
    serp = FakeLiveSource("serpapi", answering(option(300), source="serpapi"))
    ctx = alert_ctx(make_ctx, live_sources=[google, serp])
    _, tid = azores(ctx.engine)
    standout(ctx.engine, tid)
    alerts.run(ctx)
    assert serp.calls == [] and len(google.calls) == 1
    assert len(ctx.emailer.sent) == 1  # unknown sends anyway


def test_the_return_cap_survives_a_rerun(make_ctx, monkeypatch):
    google = FakeLiveSource("google_flights", answering())
    ctx = alert_ctx(make_ctx, live_sources=[google])
    _, tid = azores(ctx.engine)
    for i in range(4):
        standout(ctx.engine, tid, depart=RUN + timedelta(days=1 + i), ret=RUN + timedelta(days=10 + i))
    with session_scope(ctx.engine) as s:  # three return searches earlier today
        for rq_id in list(s.scalars(select(RouteQuery.id).order_by(RouteQuery.id)))[:3]:
            s.add(
                LiveCheck(
                    run_date=RUN, route_query_id=rq_id, source="google_flights", ok=True, purpose="return"
                )
            )
    counts = alerts.run(ctx)
    assert google.calls == [] and ctx.emailer.sent == []
    assert counts["return_checks"] == 0


# --- return rows never count as outbound checks ---


def test_a_return_row_does_not_count_as_an_outbound_check(make_ctx):
    src = FakeLiveSource("google_flights", answering(option(700)))
    ctx = make_ctx(live_sources=[src])
    add_pipeline_tracker(ctx.engine, add_pipeline_user(ctx.engine))
    expand.run(ctx)
    shortlist.run(ctx)
    with session_scope(ctx.engine) as s:
        for rq_id in s.scalars(select(ShortlistEntry.route_query_id)):
            s.add(
                LiveCheck(
                    run_date=ctx.run_date,
                    route_query_id=rq_id,
                    source="google_flights",
                    ok=True,
                    purpose="return",
                )
            )
    counts = live_verify.run(ctx)
    assert "already_checked" not in counts and counts["google_flights_ok"] == 6


def test_a_return_row_does_not_make_shortlist_treat_a_route_as_checked(make_ctx):
    from tests.pipeline.test_shortlist import DEAL, entries
    from tests.pipeline.test_shortlist import setup as shortlist_setup

    ctx = shortlist_setup(make_ctx)
    with session_scope(ctx.engine) as s:
        rq_id = s.scalar(select(RouteQuery.id).filter_by(depart_date=DEAL[0], return_date=DEAL[1]))
        s.add(
            LiveCheck(
                run_date=ctx.run_date - timedelta(days=28),
                route_query_id=rq_id,
                source="google_flights",
                ok=True,
                purpose="return",
            )
        )
    shortlist.run(ctx)
    assert entries(ctx.engine)[-1][2] != DEAL


def test_the_health_report_counts_todays_alerts(make_ctx):
    from ptopilot.pipeline.health import build_report

    ctx = alert_ctx(make_ctx)
    _, tid = azores(ctx.engine)
    standout(ctx.engine, tid)
    _, text = build_report(ctx, [])
    assert "Alerts sent today: 0" in text
    alerts.run(ctx)
    _, text = build_report(ctx, [])
    assert "Alerts sent today: 1" in text


def test_without_an_emailer_the_stage_is_skipped_before_any_search(make_ctx, monkeypatch):
    from ptopilot.pipeline.context import StageSkipped

    ctx = alert_ctx(make_ctx, emailer=None)
    _, tid = azores(ctx.engine)
    standout(ctx.engine, tid)
    monkeypatch.setattr(alerts, "check_return", lambda *a, **kw: pytest.fail("searched"))
    with pytest.raises(StageSkipped):
        alerts.run(ctx)
