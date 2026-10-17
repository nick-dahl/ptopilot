from sqlalchemy import select

from ptopilot.data import load_geo, load_seasons
from ptopilot.db.models import Candidate, DigestSend
from ptopilot.db.session import session_scope
from ptopilot.digest import __main__ as cli
from ptopilot.digest.select import build_digests
from ptopilot.digest.send import deliver
from ptopilot.notify.email import EmailError
from tests.conftest import TEST_URL
from tests.digest.conftest import MONDAY, RUN, add_candidate, add_tracker, add_user


class FakeEmailer:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def send(self, to, subject, html, text):
        if to in self.fail_for:
            raise EmailError("resend: HTTP 403: You can only send testing emails to your own email address")
        self.sent.append((to, subject))
        return "msg"


def built(engine, today=RUN):
    return build_digests(engine, load_geo(), load_seasons(), today, "good")


def sends(engine):
    with session_scope(engine) as s:
        return list(s.scalars(select(DigestSend)))


def test_send_records_the_digest_and_marks_candidates_sent(clean_engine):
    uid = add_user(clean_engine)
    cid = add_candidate(clean_engine, add_tracker(clean_engine, uid), 600)
    emailer = FakeEmailer()
    counts = deliver(clean_engine, built(clean_engine), RUN, emailer=emailer)
    assert (counts["sent"], counts["deals_sent"]) == (1, 1)
    assert emailer.sent == [("nick@example.com", "ptopilot: Azores $600")]
    [record] = sends(clean_engine)
    assert record.items == [
        {"candidate_id": cid, "tracker_id": 1, "route_query_id": 1, "evening_departure": True, "price": 600.0}
    ]
    with session_scope(clean_engine) as s:
        assert s.get(Candidate, cid).state == "sent"


def test_quiet_digest_only_goes_out_on_monday(clean_engine):
    add_tracker(clean_engine, add_user(clean_engine))
    add_candidate(clean_engine, add_tracker(clean_engine, 1, code="MADEIRA"), 900, level="none", dest="FNC")
    emailer = FakeEmailer()
    assert deliver(clean_engine, built(clean_engine), RUN, emailer=emailer)["quiet_skipped"] == 1  # Thursday
    assert deliver(clean_engine, built(clean_engine), MONDAY, emailer=emailer)["sent"] == 1
    assert emailer.sent[0][1] == "ptopilot: a quiet week for your trips"


def test_a_failed_send_is_counted_and_others_still_go_out(clean_engine):
    for email in ("nick@example.com", "friend@example.com"):
        add_candidate(clean_engine, add_tracker(clean_engine, add_user(clean_engine, email)), 600)
    emailer = FakeEmailer(fail_for={"friend@example.com"})
    counts = deliver(clean_engine, built(clean_engine), RUN, emailer=emailer)
    assert (counts["sent"], counts["failed"]) == (1, 1)
    assert [to for to, _ in emailer.sent] == ["nick@example.com"]
    assert len(sends(clean_engine)) == 1  # nothing recorded for the failed one


def test_preview_writes_files_and_touches_nothing(clean_engine, tmp_path):
    add_candidate(clean_engine, add_tracker(clean_engine, add_user(clean_engine)), 600)
    counts = deliver(clean_engine, built(clean_engine), RUN, preview_dir=tmp_path)
    assert counts["previewed"] == 1
    html = (tmp_path / f"digest-1-{RUN}.html").read_text(encoding="utf-8")
    text = (tmp_path / f"digest-1-{RUN}.txt").read_text(encoding="utf-8")
    assert "Azores" in html and text.startswith("Subject: ptopilot: Azores $600")
    assert sends(clean_engine) == []


def test_cli_requires_an_emailer_unless_previewing(clean_engine, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert cli.main(["send"]) == 2
    add_candidate(clean_engine, add_tracker(clean_engine, add_user(clean_engine)), 600)
    assert cli.main(["send", "--date", str(RUN), "--preview", str(tmp_path)]) == 0
    assert "previewed=1" in capsys.readouterr().out
    assert (tmp_path / f"digest-1-{RUN}.html").exists()


def test_rerunning_the_score_stage_does_not_cause_resends(clean_engine):
    cid = add_candidate(clean_engine, add_tracker(clean_engine, add_user(clean_engine)), 600)
    deliver(clean_engine, built(clean_engine), RUN, emailer=FakeEmailer())
    with session_scope(
        clean_engine
    ) as s:  # what a same-day `score` re-run does: delete and recreate candidates
        old = s.get(Candidate, cid)
        copied = ("user_id", "tracker_id", "route_query_id", "price_observation_id", "run_date")
        copied += (
            "evening_departure",
            "price",
            "currency",
            "z",
            "deal_level",
            "go_now",
            "confidence",
            "verified",
        )
        clone = Candidate(**{k: getattr(old, k) for k in copied})
        s.delete(old)
        s.flush()
        s.add(clone)
    assert built(clean_engine)[0].deals == []


def test_tuning_sends_record_only_real_deals(clean_engine):
    uid = add_user(clean_engine)
    t = add_tracker(clean_engine, uid)
    add_candidate(clean_engine, t, 600, level="none")
    tuning = build_digests(clean_engine, load_geo(), load_seasons(), RUN, "none")
    assert deliver(clean_engine, tuning, RUN, emailer=FakeEmailer())["sent"] == 1
    assert [s.items for s in sends(clean_engine)] == [[]]
    with session_scope(clean_engine) as s:  # the same trip later becomes a real deal at the same price
        s.query(Candidate).update({"deal_level": "good"})
    assert [c.price for c in built(clean_engine)[0].deals] == [600]


def test_tuning_digests_only_go_to_the_admin(clean_engine, monkeypatch):
    for email in ("nick@example.com", "friend@example.com"):
        add_candidate(
            clean_engine, add_tracker(clean_engine, add_user(clean_engine, email)), 600, level="none"
        )
    emailer = FakeEmailer()
    monkeypatch.setattr(cli, "ResendEmailer", lambda key, sender: emailer)
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("ADMIN_EMAIL", "Nick@Example.com")
    assert cli.main(["send", "--date", str(RUN), "--min-level", "none"]) == 0
    assert [to for to, _ in emailer.sent] == ["nick@example.com"]
    monkeypatch.delenv("ADMIN_EMAIL")
    assert cli.main(["send", "--date", str(RUN), "--min-level", "none"]) == 2  # refuses without an admin
