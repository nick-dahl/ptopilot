"""Every in-range route gets a live check each day: the cap is a safety ceiling, not a daily ration."""

from datetime import date
from pathlib import Path

import yaml

from ptopilot import config
from ptopilot.db.models import ShortlistEntry
from ptopilot.db.session import session_scope
from ptopilot.pipeline import expand, shortlist
from tests.pipeline.conftest import add_tracker, add_user

WINDOWS = tuple((date(2027, m, 1), date(2027, m, 28)) for m in (4, 5, 6, 7))
SCAN = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "scan.yml"


def test_more_than_forty_routes_are_all_shortlisted(make_ctx):
    ctx = make_ctx()
    user = add_user(ctx.engine, windows=WINDOWS)
    for code in ("LIS", "MADEIRA"):
        add_tracker(ctx.engine, user, code=code)
    expand.run(ctx)
    counts = shortlist.run(ctx)
    with session_scope(ctx.engine) as s:
        picked = s.query(ShortlistEntry).count()
    assert 40 < counts["candidates"] <= config.LIVE_CHECK_CAP
    assert picked == counts["candidates"] and counts["explore_overflow"] == 0


def test_the_cap_covers_a_full_year_of_trips():
    assert config.LIVE_CHECK_CAP >= 150


def test_the_scan_job_has_time_for_the_wider_checks():
    workflow = yaml.safe_load(SCAN.read_text(encoding="utf-8"))
    [job] = workflow["jobs"].values()
    assert job["timeout-minutes"] == 75
