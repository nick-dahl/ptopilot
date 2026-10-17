from ptopilot.links import login_token
from tests.web.conftest import KEY, invite, sign_in


def test_health_check(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/favicon.ico").status_code == 204


def test_pages_require_sign_in(client):
    for path in ("/", "/profile"):
        response = client.get(path)
        assert (response.status_code, response.headers["location"]) == (303, "/login")


def test_uninvited_email_gets_the_same_answer_and_no_email(client, emailer):
    response = client.post("/login", data={"email": "stranger@example.com"})
    assert response.status_code == 200 and "If that address is invited" in response.text
    assert emailer.sent == []


def test_invited_email_gets_a_link_that_signs_in(client, emailer, clean_engine):
    invite(clean_engine, "nick@example.com")
    response = client.post("/login", data={"email": " Nick@Example.com "})
    assert "If that address is invited" in response.text
    assert emailer.sent[0]["to"] == "nick@example.com"
    assert emailer.last_link().startswith("http://testserver/auth?token=")
    signed_in = client.get(emailer.last_link().replace("http://testserver", ""))
    assert (signed_in.status_code, signed_in.headers["location"]) == (303, "/")
    assert client.get("/").headers["location"] == "/profile"  # signed in, but no profile yet


def test_bad_and_expired_links_are_refused(client):
    assert client.get("/auth?token=garbage").status_code == 400
    forged = login_token("some-other-key", "nick@example.com")
    response = client.get(f"/auth?token={forged}")
    assert response.status_code == 400 and "not valid" in response.text
    assert client.get("/").headers["location"] == "/login"


def test_sign_out(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    assert client.post("/logout").headers["location"] == "/login"
    assert client.get("/").headers["location"] == "/login"


def test_token_for_a_valid_key_signs_in_directly(client):
    response = client.get(f"/auth?token={login_token(KEY, 'nick@example.com')}")
    assert response.status_code == 303
