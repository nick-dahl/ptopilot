from sqlalchemy import select

from ptopilot import profiles
from ptopilot.db.models import Invite
from ptopilot.db.session import session_scope
from ptopilot.digest import __main__ as digest_cli
from ptopilot.links import read_action_token
from tests.conftest import TEST_URL
from tests.digest.conftest import RUN, add_candidate, add_tracker, add_user


def test_digest_gets_snooze_buttons_when_the_web_app_is_configured(clean_engine, monkeypatch, tmp_path):
    tid = add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, tid, 600)
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.setenv("SECRET_KEY", "k")
    monkeypatch.setenv("APP_BASE_URL", "https://ptopilot.example")
    assert digest_cli.main(["send", "--date", str(RUN), "--preview", str(tmp_path)]) == 0
    text = (tmp_path / f"digest-1-{RUN}.txt").read_text(encoding="utf-8")
    link = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("Not this trip: "))
    assert link.startswith("https://ptopilot.example/s/")
    assert read_action_token("k", link.rsplit("/", 1)[1]).tracker_id == tid


def test_no_snooze_buttons_without_the_web_app(clean_engine, monkeypatch, tmp_path):
    add_candidate(clean_engine, add_tracker(clean_engine, add_user(clean_engine)), 600)
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    digest_cli.main(["send", "--date", str(RUN), "--preview", str(tmp_path)])
    assert "/s/" not in (tmp_path / f"digest-1-{RUN}.txt").read_text(encoding="utf-8")


def test_invite_command(clean_engine, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    assert profiles.main(["invite", " Friend@Example.com "]) == 0
    assert profiles.main(["invite", "Friend@Example.com"]) == 0  # idempotent
    assert profiles.main(["invite", "not-an-email"]) == 2
    with session_scope(clean_engine) as s:
        assert list(s.scalars(select(Invite.email))) == ["friend@example.com"]
    assert "invited friend@example.com" in capsys.readouterr().out
