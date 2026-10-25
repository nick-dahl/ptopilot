"""The signed-out home page: what ptopilot is, and the sign-in form."""

from tests.web.conftest import is_landing, sign_in


def test_signed_out_home_is_the_landing_page_with_sign_in(client):
    page = client.get("/")
    assert is_landing(page)
    assert "Your PTO, spent on the right trips" in page.text
    assert 'action="/login"' in page.text and 'type="email"' in page.text
    assert "How it works" in page.text and "Invite-only" in page.text


def test_sample_cards_are_labelled_examples_not_real_trips(client):
    page = client.get("/").text
    assert page.count("Example</span>") == 2
    assert "Azores" in page and "Patagonia" in page and "below typical" in page


def test_old_sign_in_address_redirects_home(client):
    response = client.get("/login")
    assert (response.status_code, response.headers["location"]) == (303, "/")


def test_signing_in_from_the_landing_form_still_works(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    assert client.get("/").headers["location"] == "/profile"  # signed in, no profile yet


def test_landing_does_not_need_the_database(clean_engine, emailer, monkeypatch):
    from fastapi.testclient import TestClient

    import ptopilot.web.app as app_module
    from ptopilot.data import load_geo
    from ptopilot.settings import Settings
    from tests.web.conftest import KEY, TODAY

    def geo(engine=None):
        if engine is not None:
            raise RuntimeError("database down")
        return load_geo()

    monkeypatch.setattr(app_module, "load_geo", geo)
    settings = Settings(database_url="unused", secret_key=KEY, app_base_url="http://testserver")
    app = app_module.create_app(settings, engine=clean_engine, emailer=emailer, today=lambda: TODAY)
    with TestClient(app, follow_redirects=False) as c:
        page = c.get("/")
    assert page.status_code == 200 and "Azores" in page.text
