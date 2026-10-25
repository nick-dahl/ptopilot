"""The shared look: one stylesheet, the base layout, and friendly pages for malformed requests."""

import tomllib
from datetime import date
from pathlib import Path

from ptopilot.digest.render import date_range
from tests.web.conftest import sign_in

ROOT = Path(__file__).resolve().parents[2]


def test_stylesheet_is_served(client):
    response = client.get("/static/app.css")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/css")
    assert "--bg: #fbf7f0" in response.text


def test_pages_use_the_stylesheet_and_fonts(client):
    page = client.get("/s/not-a-token").text
    assert '<link rel="stylesheet" href="/static/app.css">' in page
    assert "family=Fraunces" in page and "family=Inter" in page


def test_stylesheet_ships_with_the_package():
    package_data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"][
        "package-data"
    ]
    assert "static/*.css" in package_data["ptopilot.web"]


def test_malformed_form_input_gets_a_page_not_json(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    response = client.post("/trackers/1/snooze", data={"days": "lots"})
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "didn&#39;t look right" in response.text and "/static/app.css" in response.text


def test_malformed_path_gets_a_page_not_json(client, emailer, clean_engine):
    sign_in(client, emailer, clean_engine)
    response = client.post("/trackers/not-a-number/snooze")
    assert response.status_code == 400 and "didn&#39;t look right" in response.text


def test_date_range_is_compact():
    assert date_range(date(2027, 3, 5), date(2027, 3, 15)) == "Mar 5–15"
    assert date_range(date(2027, 2, 27), date(2027, 3, 14)) == "Feb 27–Mar 14"
    assert date_range(date(2027, 12, 28), date(2028, 1, 4)) == "Dec 28, 2027–Jan 4, 2028"
