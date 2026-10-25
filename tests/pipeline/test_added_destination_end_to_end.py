"""A place added on the website is planned, scanned and dated by its generated seasons."""

import json
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ptopilot.core.airports import AirportCatalog
from ptopilot.db.models import PlanningYear, RouteQuery, TrackerRouteLink, TravelWindow
from ptopilot.db.session import session_scope
from ptopilot.destinations import add_destination
from ptopilot.pipeline import context as context_module
from ptopilot.pipeline import expand
from ptopilot.settings import Settings
from tests.db.test_models import make_user
from tests.pipeline.conftest import RUN

TOKYO = json.loads(
    (Path(__file__).parents[1] / "sources" / "fixtures" / "real_open_meteo_tokyo_2011_2020.json").read_text(
        encoding="utf-8"
    )
)


def test_a_destination_added_on_the_website_is_planned_scanned_and_dated_by_its_climate(
    clean_engine, monkeypatch
):
    with Session(clean_engine) as s:
        user = make_user(s, home_airport="JFK")
        s.add(TravelWindow(user_id=user.id, start_date=date(2027, 10, 1), end_date=date(2027, 10, 31)))
        s.add(PlanningYear(user_id=user.id, year=2027, pto_days=15))
        osaka = AirportCatalog.load().search("Osaka")[0]
        add_destination(s, user, osaka, ["KIX", "ITM"], 12, climate=lambda lat, lon: TOKYO, today=RUN)
        s.commit()

    monkeypatch.setattr(context_module, "make_engine", lambda url: clean_engine)
    ctx = context_module.build_context(Settings(database_url="unused"), RUN)
    assert expand.run(ctx)["trackers"] == 1

    with session_scope(clean_engine) as s:
        rows = s.execute(
            select(TrackerRouteLink, RouteQuery)
            .join(RouteQuery)
            .where(TrackerRouteLink.tracker_id.is_not(None))
        ).all()
        assert rows
        assert ("JFK", "KIX") in {(rq.origin, rq.dest_airport) for _, rq in rows}
        for link, rq in rows:
            assert 10 <= link.days_away <= 14
            assert link.days_away >= 7  # NA - E_ASIA route minimum
            assert link.season_rating == "good"
            assert rq.depart_date.month == 10
