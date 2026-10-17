from datetime import date

import pytest
from itsdangerous import URLSafeTimedSerializer

from ptopilot.links import (
    Action,
    TokenError,
    action_links,
    action_token,
    login_token,
    read_action_token,
    read_login_token,
)

KEY = "test-secret"


def test_login_token_round_trip_and_normalises_email():
    assert read_login_token(KEY, login_token(KEY, " Nick@Example.com ")) == "nick@example.com"


def test_expired_and_tampered_tokens_are_rejected():
    token = login_token(KEY, "nick@example.com")
    with pytest.raises(TokenError, match="expired"):
        read_login_token(KEY, token, max_age=-1)
    with pytest.raises(TokenError, match="not valid"):
        read_login_token("other-secret", token)
    with pytest.raises(TokenError, match="not valid"):
        read_action_token(KEY, token)  # a login token is not an action token (different salt)


def test_action_token_round_trip():
    action = Action(7, "trip", date(2027, 3, 5), date(2027, 3, 14))
    assert read_action_token(KEY, action_token(KEY, action)) == action
    assert read_action_token(KEY, action_token(KEY, Action(7, "snooze30"))) == Action(7, "snooze30")


def test_unknown_action_kind_is_rejected():
    forged = URLSafeTimedSerializer(KEY, salt="action").dumps({"t": 7, "a": "delete_everything"})
    with pytest.raises(TokenError):
        read_action_token(KEY, forged)


def test_action_links_cover_every_button():
    links = action_links("https://app.example", KEY, 7, date(2027, 3, 5), date(2027, 3, 14))
    labels = [label for label, _ in links]
    assert labels == ["Not this trip", "Snooze 30 days", "Not this year", "Only if under $…"]
    assert all(url.startswith("https://app.example/s/") for _, url in links)
    assert read_action_token(KEY, links[0][1].rsplit("/", 1)[1]).kind == "trip"


def test_missing_secret_is_a_clear_error():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        login_token("", "nick@example.com")
