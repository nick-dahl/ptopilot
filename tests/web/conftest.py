"""Web app fixtures: the app on the test database, a capturing emailer, and a sign-in helper."""

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import insert

from ptopilot.data import load_geo
from ptopilot.db.models import Invite
from ptopilot.db.session import session_scope
from ptopilot.profiles import apply_profile, parse_profile
from ptopilot.settings import Settings
from ptopilot.web.app import create_app
from ptopilot.web.forms import form_to_profile

TODAY = date(2027, 3, 4)
KEY = "test-secret-key"


class CapturingEmailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, html, text):
        self.sent.append({"to": to, "subject": subject, "text": text})
        return "msg"

    def last_link(self) -> str:
        return re.search(r"https?://\S+", self.sent[-1]["text"]).group(0)


@pytest.fixture
def emailer():
    return CapturingEmailer()


@pytest.fixture
def client(clean_engine, emailer):
    settings = Settings(database_url="unused", secret_key=KEY, app_base_url="http://testserver")
    app = create_app(settings, engine=clean_engine, emailer=emailer, today=lambda: TODAY)
    with TestClient(app, follow_redirects=False) as c:
        yield c


def invite(engine, email):
    with session_scope(engine) as s:
        s.execute(insert(Invite).values(email=email).on_conflict_do_nothing())


def is_landing(response) -> bool:
    """The signed-out home page: the product pitch with the sign-in form."""
    return response.status_code == 200 and 'id="sign-in"' in response.text


def sign_in(client, emailer, engine, email="nick@example.com"):
    invite(engine, email)
    client.post("/login", data={"email": email})
    link = emailer.last_link()
    response = client.get(link.replace("http://testserver", ""))
    assert response.status_code == 303
    return response


PROFILE_FORM = {
    "home_airport": "jfk",
    "nearby_airports": "EWR, PHL",
    "country": "US",
    "holiday_calendar": "US",
    "ignored_holidays": "Columbus Day, Veterans Day",
    "extra_days_off": "",
    "pto_days_total": "22",
    "min_trip_days": "7",
    "max_trip_days": "16",
    "weather_tolerance": "normal",
    "max_stops_short": "3",
    "max_stops_long": "3",
    "friday_evening_min_time": "17:00",
    "allow_overnight_layover": "on",
    "friday_evening_departure": "on",
    "window_start_0": "2027-03-01",
    "window_end_0": "2027-03-31",
    "window_start_1": "",
    "window_end_1": "",
    "tracker_dest_0": "AZORES",
    "tracker_min_0": "7",
    "tracker_max_0": "10",
    "tracker_priority_0": "1",
    "tracker_price_0": "",
    "tracker_dest_1": "",
    "tracker_min_1": "",
    "tracker_max_1": "",
    "tracker_priority_1": "2",
    "tracker_price_1": "",
}


def seed_profile(engine, form=None, email="nick@example.com"):
    """Save a full profile (windows, planning years, trackers) the way the YAML loader does.

    The web profile form no longer carries windows or the bucket list, so tests that need a
    planned year go through apply_profile directly.
    """
    form = {**PROFILE_FORM, "pto_committed": "7", **(form or {})}
    profile = parse_profile(form_to_profile(form, email), load_geo(engine))
    with session_scope(engine) as s:
        apply_profile(s, profile)
