from datetime import date, timedelta

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
        ("alerts", "skipped"),  # no emailer configured
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
    assert [r.status for r in results] == ["ok", "failed"] + ["not_run"] * 6
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
        "alerts": "skipped",
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
