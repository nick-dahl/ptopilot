"""Database fixtures. Uses PTOPILOT_TEST_DATABASE_URL, defaulting to the local dev server on port 5433.

Tests skip when the database is unreachable, unless PTOPILOT_REQUIRE_DB is set (CI sets it).
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ptopilot.db.session import make_engine
from ptopilot.settings import normalize_database_url

TEST_URL = normalize_database_url(
    os.environ.get("PTOPILOT_TEST_DATABASE_URL", "postgresql://ptopilot@localhost:5433/ptopilot_test")
)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def engine():
    eng = make_engine(TEST_URL)
    try:
        with eng.connect():
            pass
    except OperationalError as exc:
        if os.environ.get("PTOPILOT_REQUIRE_DB"):
            raise
        pytest.skip(
            f"test database unavailable ({type(exc).__name__}); start it or set PTOPILOT_TEST_DATABASE_URL"
        )
    cfg = alembic_config(TEST_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """A session whose work is rolled back after the test, even if the test commits."""
    with engine.connect() as conn:
        outer = conn.begin()
        s = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            s.close()
            outer.rollback()
