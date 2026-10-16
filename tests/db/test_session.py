import time

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from ptopilot.db import session as session_module
from ptopilot.db.models import Invite
from ptopilot.db.session import make_engine, session_scope


def test_unreachable_database_fails_fast_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(session_module, "CONNECT_TIMEOUT_S", 2)
    start = time.monotonic()
    with pytest.raises(OperationalError):
        make_engine("postgresql+psycopg://ptopilot@127.0.0.1:5999/nope").connect()
    assert time.monotonic() - start < 10


def emails(engine):
    with session_scope(engine) as s:
        return set(s.scalars(select(Invite.email)))


def test_session_scope_commits_on_success(engine):
    try:
        with session_scope(engine) as s:
            s.add(Invite(email="commit@example.com"))
        assert "commit@example.com" in emails(engine)
    finally:
        with session_scope(engine) as s:
            s.execute(delete(Invite).where(Invite.email == "commit@example.com"))


def test_session_scope_rolls_back_on_error(engine):
    with pytest.raises(RuntimeError), session_scope(engine) as s:
        s.add(Invite(email="rollback@example.com"))
        s.flush()
        raise RuntimeError("boom")
    assert "rollback@example.com" not in emails(engine)
