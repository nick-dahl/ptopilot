from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from ptopilot.db.models import Candidate, PipelineRun, RouteQuery
from ptopilot.db.session import session_scope
from ptopilot.pipeline import __main__ as cli
from ptopilot.pipeline import runner
from ptopilot.pipeline.context import StageFailed
from ptopilot.pipeline.health import build_report, send_report
from tests.pipeline.conftest import (
    RUN,
    FakeLiveSource,
    FakeMonthSource,
    add_observation,
    add_tracker,
    add_user,
    answering,
    failing,
    option,
    quote,
)

DEAL = (date(2027, 6, 12), date(2027, 6, 20))


class FakeEmailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, html, text):
        self.sent.append((to, subject, text))
        return "msg_1"


def runs(engine):
    with session_scope(engine) as s:
        return {r.stage: r for r in s.scalars(select(PipelineRun))}


def test_end_to_end_finds_a_great_deal(make_ctx):
    """History: June ORD-LIS week trips cost ~$1000. Today's live price for the Juneteenth trip is $590."""
    ctx = make_ctx(
        month_source=FakeMonthSource({("ORD", "LIS", date(2027, 6, 1)): [quote("ORD", "LIS", *DEAL, 610)]}),
        live_sources=[FakeLiveSource("google_flights", answering(option(590), option(640, stops=0)))],
    )
    add_tracker(ctx.engine, add_user(ctx.engine))
    for i, price in enumerate([950, 1000, 1050, 980, 1020] * 4):  # 20 days of history
        add_observation(ctx.engine, *DEAL, price, observed=RUN - timedelta(days=40 - i))

    results = runner.run_pipeline(ctx)

    assert [(r.stage, r.status) for r in results] == [
        ("expand", "ok"),
        ("broad_scan", "ok"),
        ("shortlist", "ok"),
        ("seed_history", "skipped"),  # no history source among the fakes
        ("live_verify", "ok"),
        ("baselines", "ok"),
        ("score", "ok"),
        ("related", "ok"),  # nothing accepted: a quiet watch
        ("gems", "ok"),  # the shipped catalogue has no approved gems yet: a quiet no-op
        ("photos", "skipped"),  # no Wikimedia client among the fakes
        ("alerts", "skipped"),  # no emailer configured
        ("prune", "ok"),
    ]
    with session_scope(ctx.engine) as s:
        rows = s.execute(select(Candidate, RouteQuery).join(RouteQuery)).all()
        deal = next(c for c, rq in rows if (rq.depart_date, rq.return_date) == DEAL)
        assert (deal.price, deal.verified, deal.deal_level, deal.confidence) == (590, True, "great", "normal")
    assert set(runs(ctx.engine)) == set(runner.STAGES)


def test_failed_core_stage_stops_the_rest(make_ctx, monkeypatch):
    def broken(ctx):
        raise StageFailed("all month scans failed")

    monkeypatch.setitem(runner.STAGES, "broad_scan", broken)
    results = runner.run_pipeline(make_ctx())
    assert [r.status for r in results] == ["ok", "failed"] + ["not_run"] * 10
    assert runs(make_ctx().engine)["broad_scan"].error == "all month scans failed"


def test_live_verify_failure_lets_scoring_continue(make_ctx):
    ctx = make_ctx(live_sources=[FakeLiveSource("google_flights", failing())])
    add_tracker(ctx.engine, add_user(ctx.engine))
    statuses = {r.stage: r.status for r in runner.run_pipeline(ctx)}
    assert statuses == {
        "expand": "ok",
        "broad_scan": "skipped",
        "shortlist": "ok",
        "seed_history": "skipped",
        "live_verify": "failed",
        "baselines": "ok",
        "score": "ok",
        "related": "skipped",  # no month source
        "gems": "ok",  # nothing approved to publish
        "photos": "skipped",  # no Wikimedia client
        "alerts": "skipped",
        "prune": "ok",
    }


def test_unexpected_crash_is_recorded(make_ctx, monkeypatch):
    monkeypatch.setitem(runner.STAGES, "expand", lambda ctx: 1 / 0)
    result = runner.run_stage(make_ctx(), "expand")
    assert result.status == "failed"
    assert "ZeroDivisionError" in result.error


def test_unknown_stage_is_rejected(make_ctx):
    with pytest.raises(ValueError, match="nope"):
        runner.run_pipeline(make_ctx(), ["nope"])


def test_health_report_summarises_stages_and_budget(make_ctx):
    ctx = make_ctx()
    results = [
        runner.StageResult("expand", "ok", {"links": 6}),
        runner.StageResult("live_verify", "failed", {"google_flights_failed": 3}, "no live check succeeded"),
    ]
    subject, text = build_report(ctx, results)
    assert subject == "ptopilot scan 2027-03-01: FAILED (live_verify)"
    assert "links=6" in text and "no live check succeeded" in text
    assert "serpapi: 0/250 this month (250 left)" in text


def test_health_report_labels_skip_reasons_as_reasons(make_ctx):
    _, text = build_report(make_ctx(), [runner.StageResult("broad_scan", "skipped", error="no token")])
    assert "reason: no token" in text and "error:" not in text


def test_report_is_emailed_unless_dry_run(make_ctx):
    emailer = FakeEmailer()
    results = [runner.StageResult("expand", "ok")]
    send_report(make_ctx(emailer=emailer, admin_email="me@example.com", dry_run=True), results)
    assert emailer.sent == []
    send_report(make_ctx(emailer=emailer, admin_email="me@example.com"), results)
    assert emailer.sent[0][:2] == ("me@example.com", "ptopilot scan 2027-03-01: OK")


def test_cli_runs_selected_stages_and_exit_code_reflects_failures(make_ctx, monkeypatch, capsys):
    ctx = make_ctx()
    monkeypatch.setattr(cli, "build_context", lambda settings, run_date, dry_run: ctx)
    assert cli.main(["run", "--stage", "expand", "--date", "2027-03-01", "--dry-run"]) == 0
    assert "expand" in capsys.readouterr().out

    monkeypatch.setitem(runner.STAGES, "expand", lambda c: 1 / 0)
    assert cli.main(["run", "--stage", "expand"]) == 1


def test_each_stage_result_has_its_duration(make_ctx, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(runner, "monotonic", lambda: now[0])

    def slow(ctx):
        now[0] += 42
        return {}

    monkeypatch.setitem(runner.STAGES, "expand", slow)
    results = runner.run_pipeline(make_ctx(), ["expand"])
    assert results[0].seconds == 42


def test_health_report_shows_durations(make_ctx):
    results = [
        runner.StageResult("expand", "ok", seconds=125.4),
        runner.StageResult("shortlist", "ok", seconds=8.2),
        runner.StageResult("baselines", "ok"),
    ]
    _, text = build_report(make_ctx(), results)
    line = {name: next(ln for ln in text.splitlines() if name in ln) for name in ("expand", "shortlist")}
    assert "2m05s" in line["expand"] and "8s" in line["shortlist"]
    baselines = next(ln for ln in text.splitlines() if "baselines" in ln)
    assert baselines.strip() == "baselines    ok"


def test_a_new_run_marks_leftover_running_stages_interrupted(make_ctx, monkeypatch, capsys):
    ctx = make_ctx()
    with session_scope(ctx.engine) as s:
        s.add(PipelineRun(run_date=date(2027, 2, 28), stage="live_verify", status="running"))
    monkeypatch.setattr(cli, "build_context", lambda settings, run_date, dry_run: ctx)

    assert cli.main(["run", "--dry-run", "--stage", "expand"]) == 0

    old = runs(ctx.engine)["live_verify"]
    assert old.status == "interrupted"
    assert old.error == "the run was stopped before this stage finished"
    assert old.finished_at is not None
    assert "Interrupted earlier: 2027-02-28 live_verify" in capsys.readouterr().out


def test_interrupted_command_marks_and_emails(make_ctx, monkeypatch):
    emailer = FakeEmailer()
    ctx = make_ctx(emailer=emailer, admin_email="me@example.com")
    monkeypatch.setattr(cli, "build_context", lambda settings, run_date, dry_run: ctx)

    assert cli.main(["interrupted"]) == 0  # nothing running: no email
    assert emailer.sent == []

    with session_scope(ctx.engine) as s:
        s.add(PipelineRun(run_date=date(2027, 2, 28), stage="live_verify", status="running"))
    assert cli.main(["interrupted"]) == 1
    assert runs(ctx.engine)["live_verify"].status == "interrupted"
    assert len(emailer.sent) == 1
    to, subject, _ = emailer.sent[0]
    assert (to, subject) == ("me@example.com", "ptopilot scan 2027-02-28: INTERRUPTED (live_verify)")


# --- Plan 18 Task 5: three runs a day ---------------------------------------------------------------


def _fake_stages(monkeypatch):
    calls = []
    for name in runner.STAGES:
        monkeypatch.setitem(runner.STAGES, name, lambda ctx, n=name: calls.append(n) or {})
    return calls


def test_once_a_day_stages_skip_on_a_later_run(make_ctx, monkeypatch):
    calls = _fake_stages(monkeypatch)
    ctx = make_ctx()
    runner.run_pipeline(ctx)
    calls.clear()

    second = {r.stage: r for r in runner.run_pipeline(ctx)}

    for name in runner.ONCE_A_DAY:
        assert (second[name].status, second[name].error) == ("skipped", "already ran today")
    assert "score" in calls and "live_verify" in calls
    assert not set(calls) & runner.ONCE_A_DAY

    calls.clear()
    assert runner.run_pipeline(ctx, ["broad_scan"])[0].status == "ok"
    assert calls == ["broad_scan"]


def test_a_once_a_day_stage_that_failed_runs_again(make_ctx, monkeypatch):
    calls = _fake_stages(monkeypatch)
    monkeypatch.setitem(runner.STAGES, "gems", lambda ctx: 1 / 0)
    ctx = make_ctx()
    runner.run_pipeline(ctx)
    monkeypatch.setitem(runner.STAGES, "gems", lambda ctx: calls.append("gems") or {})
    assert {r.stage: r.status for r in runner.run_pipeline(ctx)}["gems"] == "ok"


def _add_trips(engine, run_date, total, fresh, route_specific_misses=0, longest_ago=None, shift=0):
    """`total` in-horizon route queries linked on run_date; the first `fresh` have an ok check that day."""
    from ptopilot.db.models import LiveCheck, Tracker, TrackerRouteLink

    with session_scope(engine) as s:
        tracker_id = s.scalar(select(Tracker.id))
        for i in range(total):
            depart = run_date + timedelta(days=10 + i % 20)
            rq = RouteQuery(
                origin="ORD",
                dest_airport="LIS",
                return_airport="LIS",
                depart_date=depart,
                return_date=depart + timedelta(days=6 + shift + i // 20),
            )
            s.add(rq)
            s.flush()
            s.add(
                TrackerRouteLink(
                    tracker_id=tracker_id,
                    route_query_id=rq.id,
                    run_date=run_date,
                    pto_cost=3,
                    month=depart.month,
                    season_rating="ok",
                    days_away=7,
                    efficiency=1.0,
                )
            )
            if i < fresh:
                s.add(LiveCheck(run_date=run_date, route_query_id=rq.id, source="google_flights", ok=True))
            elif i < fresh + route_specific_misses:
                s.add(
                    LiveCheck(
                        run_date=run_date,
                        route_query_id=rq.id,
                        source="google_flights",
                        ok=False,
                        route_specific=True,
                    )
                )
            elif longest_ago is not None and i == total - 1:
                # one older fresh price, so "longest wait" is measurable
                s.add(
                    LiveCheck(
                        run_date=run_date - timedelta(days=longest_ago),
                        route_query_id=rq.id,
                        source="google_flights",
                        ok=True,
                        checked_at=datetime.combine(
                            run_date - timedelta(days=longest_ago), time(12), tzinfo=UTC
                        ),
                    )
                )


def _with_tracker(make_ctx, **kw):
    ctx = make_ctx(**kw)
    add_tracker(ctx.engine, add_user(ctx.engine))
    return ctx


LIVE_COUNTS = {
    "first_checks": 120,
    "second_checks": 30,
    "audits": 2,
    "google_flights_ok": 100,
    "google_flights_failed": 3,
    "google_flights_route_failed": 1,
    "google_flights_empty": 27,
    "no_flights": 40,  # SerpApi's empties too: Google's empty share uses only its own
}


def test_health_report_shows_freshness(make_ctx):
    ctx = _with_tracker(make_ctx)
    _add_trips(ctx.engine, RUN, total=260, fresh=250)
    _, text = build_report(ctx, [runner.StageResult("live_verify", "ok", dict(LIVE_COUNTS))])
    assert "Fresh today: 250 of 260 in horizon (10 not yet)" in text
    assert "Checks this run: 120 first, 30 second, 2 audit" in text
    assert "Google: 4% failed, 27% empty" in text
    assert "back-off" not in text

    slowed = dict(LIVE_COUNTS, backoff_slowed=1)
    _, text = build_report(ctx, [runner.StageResult("live_verify", "ok", slowed)])
    assert "back-off: slowed" in text


def test_freshness_check_lines_only_when_live_verify_ran(make_ctx):
    _, text = build_report(_with_tracker(make_ctx), [runner.StageResult("expand", "ok")])
    assert "Fresh today:" in text and "Checks this run" not in text and "Google:" not in text


def _mark_emailed(engine):
    with session_scope(engine) as s:
        s.add(PipelineRun(run_date=RUN, stage="health_email", status="ok"))


def _mark_emailed_off(engine):
    with session_scope(engine) as s:
        for row in s.scalars(select(PipelineRun).where(PipelineRun.stage == "health_email")):
            s.delete(row)


def test_first_run_warns_about_yesterday(make_ctx):
    ctx = _with_tracker(make_ctx)
    yesterday = RUN - timedelta(days=1)
    _add_trips(ctx.engine, yesterday, total=15, fresh=3, longest_ago=2)
    subject, text = build_report(ctx, [runner.StageResult("expand", "ok")])
    assert "12 trips had no live price yesterday (longest: 2 days)" in text
    assert subject == "ptopilot scan 2027-03-01: OK — 12 trips stale"

    # once the day's email went out, later runs neither warn nor change the subject
    _mark_emailed(ctx.engine)
    subject, text = build_report(ctx, [runner.StageResult("live_verify", "ok", dict(LIVE_COUNTS))])
    assert "yesterday" not in text and subject == "ptopilot scan 2027-03-01: OK"

    # a manual --stage run never carries it
    _mark_emailed_off(ctx.engine)
    _, text = build_report(ctx, [runner.StageResult("alerts", "ok")], full_run=False)
    assert "yesterday" not in text


def test_unpriceable_trips_are_listed_not_warned(make_ctx):
    ctx = _with_tracker(make_ctx)
    _add_trips(ctx.engine, RUN - timedelta(days=1), total=10, fresh=7, route_specific_misses=3)
    subject, text = build_report(ctx, [runner.StageResult("expand", "ok")])
    assert "Google can't price 3 trips" in text
    assert "no live price yesterday" not in text
    assert subject == "ptopilot scan 2027-03-01: OK"


def test_later_runs_email_only_on_trouble(make_ctx):
    emailer = FakeEmailer()
    ctx = _with_tracker(make_ctx, emailer=emailer, admin_email="me@example.com")
    _add_trips(ctx.engine, RUN, total=5, fresh=5)
    _mark_emailed(ctx.engine)  # the day's first email already went out
    later = [runner.StageResult("live_verify", "ok", dict(LIVE_COUNTS))]
    noon = datetime(2027, 3, 1, 14, tzinfo=UTC)
    night = datetime(2027, 3, 1, 22, 5, tzinfo=UTC)

    send_report(ctx, later, now=noon)
    send_report(ctx, later, now=night)  # everything fresh: still quiet
    assert emailer.sent == []

    send_report(ctx, [*later, runner.StageResult("alerts", "failed", error="x")], now=noon)
    assert len(emailer.sent) == 1
    send_report(
        ctx, [runner.StageResult("live_verify", "ok", dict(LIVE_COUNTS, backoff_stopped=4))], now=noon
    )
    assert len(emailer.sent) == 2

    _add_trips(ctx.engine, RUN, total=3, fresh=0, shift=5)  # trips still without a price
    send_report(ctx, later, now=noon)
    assert len(emailer.sent) == 2
    send_report(ctx, later, now=night)
    assert len(emailer.sent) == 3

    # a manual --stage run is not the day's first email either
    _mark_emailed_off(ctx.engine)
    send_report(ctx, [runner.StageResult("alerts", "ok")], now=noon, full_run=False)
    assert len(emailer.sent) == 3
    send_report(ctx, [runner.StageResult("expand", "ok")], now=noon)  # the first full run always emails
    assert len(emailer.sent) == 4


def test_a_dry_run_does_not_count_as_ran_today(make_ctx, monkeypatch):
    calls = _fake_stages(monkeypatch)
    runner.run_pipeline(make_ctx(dry_run=True))
    assert {r.status for r in runs(make_ctx().engine).values()} == {"dry_run"}
    calls.clear()
    second = {r.stage: r for r in runner.run_pipeline(make_ctx())}
    assert all(second[n].status == "ok" for n in runner.ONCE_A_DAY)
    assert runner.ONCE_A_DAY <= set(calls)


class FlakyEmailer(FakeEmailer):
    fail = True

    def send(self, to, subject, html, text):
        if self.fail:
            raise RuntimeError("resend is down")
        return super().send(to, subject, html, text)


def test_yesterday_warning_survives_a_crashed_first_run(make_ctx):
    emailer = FlakyEmailer()
    ctx = _with_tracker(make_ctx, emailer=emailer, admin_email="me@example.com")
    _add_trips(ctx.engine, RUN - timedelta(days=1), total=5, fresh=2)
    noon = datetime(2027, 3, 1, 14, tzinfo=UTC)
    with pytest.raises(RuntimeError):
        send_report(ctx, [runner.StageResult("expand", "ok")], now=datetime(2027, 3, 1, 6, tzinfo=UTC))
    emailer.fail = False
    send_report(ctx, [runner.StageResult("live_verify", "ok", dict(LIVE_COUNTS))], now=noon)
    assert "3 trips had no live price yesterday" in emailer.sent[0][2]
    assert emailer.sent[0][1].endswith("— 3 trips stale")


def test_yesterday_warning_is_sent_once_per_day(make_ctx):
    emailer = FakeEmailer()
    ctx = _with_tracker(make_ctx, emailer=emailer, admin_email="me@example.com")
    _add_trips(ctx.engine, RUN - timedelta(days=1), total=5, fresh=2)
    send_report(ctx, [runner.StageResult("expand", "ok")], now=datetime(2027, 3, 1, 6, tzinfo=UTC))
    assert len(emailer.sent) == 1
    send_report(
        ctx,
        [runner.StageResult("live_verify", "ok", dict(LIVE_COUNTS))],
        now=datetime(2027, 3, 1, 14, tzinfo=UTC),
    )
    assert len(emailer.sent) == 1
    assert "health_email" not in runner.STAGES


def test_failed_live_verify_still_reports_its_checks(make_ctx):
    ctx = _with_tracker(make_ctx)
    counts = {"first_checks": 3, "google_flights_failed": 3, "google_flights_breaker_tripped": 1}
    _, text = build_report(ctx, [runner.StageResult("live_verify", "failed", counts, error="no live check")])
    assert "Checks this run: 3 first, 0 second, 0 audit" in text
    assert "Google: 100% failed, 0% empty" in text


def test_a_failed_live_verify_keeps_its_counts(make_ctx):
    ctx = make_ctx(live_sources=[FakeLiveSource("google_flights", failing("429"))])
    add_tracker(ctx.engine, add_user(ctx.engine))
    runner.run_stage(ctx, "expand")
    runner.run_stage(ctx, "shortlist")
    result = runner.run_stage(ctx, "live_verify")
    assert result.status == "failed" and result.counts["google_flights_failed"] == 3
    assert runs(ctx.engine)["live_verify"].counts["first_checks"] == 3


def test_one_stale_trip_is_singular_in_the_subject(make_ctx):
    ctx = _with_tracker(make_ctx)
    _add_trips(ctx.engine, RUN - timedelta(days=1), total=3, fresh=2)
    subject, _ = build_report(ctx, [runner.StageResult("expand", "ok")])
    assert subject == "ptopilot scan 2027-03-01: OK — 1 trip stale"
