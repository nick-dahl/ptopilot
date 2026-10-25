from datetime import date

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from ptopilot.db.models import Base
from tests.conftest import TEST_URL, alembic_config


def test_upgrade_creates_every_model_table(engine):
    tables = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables) <= tables


def test_models_and_migrations_agree(engine):
    """Fails if someone edits models.py without generating a migration."""
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(ctx, Base.metadata) == []


@pytest.fixture
def at_0006(engine):
    """The database downgraded to revision 0006, restored to head (and emptied) afterwards."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    cfg = alembic_config(TEST_URL)
    command.downgrade(cfg, "0006")
    try:
        yield cfg
    finally:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
        command.upgrade(cfg, "head")


def _insert_user_with_trackers(conn, windows, trackers):
    user_id = conn.execute(
        text(
            "INSERT INTO users (email, home_airport, country, holiday_calendar, pto_days_total,"
            " pto_committed, max_trip_days) VALUES ('m@example.com', 'ORD', 'US', 'US', 15, 2, 16)"
            " RETURNING id"
        )
    ).scalar_one()
    for start, end in windows:
        conn.execute(
            text("INSERT INTO travel_windows (user_id, start_date, end_date) VALUES (:u, :s, :e)"),
            {"u": user_id, "s": start, "e": end},
        )
    for code, active in trackers:
        conn.execute(
            text(
                "INSERT INTO trackers (user_id, destination_code, min_stay_days, max_stay_days, active)"
                " VALUES (:u, :c, 5, 9, :a)"
            ),
            {"u": user_id, "c": code, "a": active},
        )
    return user_id


def test_migration_seeds_planning_years_and_trips_from_windows(engine, at_0006):
    with engine.begin() as conn:
        user_id = _insert_user_with_trackers(
            conn,
            [
                (date(2027, 3, 1), date(2027, 3, 21)),
                (date(2027, 10, 1), date(2027, 10, 21)),
                (date(2028, 2, 1), date(2028, 2, 10)),
            ],
            [("TH", True), ("PT", True), ("JP", False)],
        )
    command.upgrade(at_0006, "0007")
    with engine.connect() as conn:
        years = conn.execute(
            text("SELECT user_id, year, pto_days, other_time_off FROM planning_years ORDER BY year")
        ).all()
        assert years == [(user_id, 2027, 15, 2), (user_id, 2028, 15, 2)]
        trips = conn.execute(
            text(
                "SELECT t.destination_code, p.year FROM planned_trips p"
                " JOIN trackers t ON t.id = p.tracker_id ORDER BY p.year, t.destination_code"
            )
        ).all()
        assert trips == [("PT", 2027), ("TH", 2027), ("PT", 2028), ("TH", 2028)]


def test_migration_refuses_duplicate_trackers_and_changes_nothing(engine, at_0006):
    with engine.begin() as conn:
        _insert_user_with_trackers(conn, [], [("TH", True), ("TH", False)])
    with pytest.raises(RuntimeError, match="1 duplicate"):
        command.upgrade(at_0006, "0007")
    assert "planning_years" not in inspect(engine).get_table_names()


def test_migration_downgrade_drops_the_new_tables(engine):
    cfg = alembic_config(TEST_URL)
    command.downgrade(cfg, "0006")
    try:
        tables = set(inspect(engine).get_table_names())
        assert "planning_years" not in tables
        assert "planned_trips" not in tables
    finally:
        command.upgrade(cfg, "head")
