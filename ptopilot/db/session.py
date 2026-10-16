"""Engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

CONNECT_TIMEOUT_S = 15


def make_engine(database_url: str) -> Engine:
    # pool_pre_ping: Neon's free tier suspends idle compute, which drops pooled connections.
    # connect_timeout: without it, psycopg on Windows waits forever on an unreachable server.
    return create_engine(
        database_url, pool_pre_ping=True, connect_args={"connect_timeout": CONNECT_TIMEOUT_S}
    )


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit on success, roll back on any exception."""
    session = sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
