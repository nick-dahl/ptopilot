import pytest

from ptopilot.settings import DEV_DATABASE_URL, Settings, normalize_database_url


def test_defaults_point_at_local_dev_database():
    s = Settings.from_env({})
    assert s.database_url == DEV_DATABASE_URL
    assert (s.travelpayouts_token, s.serpapi_key) == ("", "")


def test_reads_secrets_from_env():
    s = Settings.from_env({"TRAVELPAYOUTS_TOKEN": "t", "SERPAPI_KEY": "k"})
    assert (s.travelpayouts_token, s.serpapi_key) == ("t", "k")


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "postgresql://u:p@ep-x.neon.tech/db?sslmode=require",
            "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require",
        ),
        ("postgres://u@h/db", "postgresql+psycopg://u@h/db"),
        ("postgresql+psycopg://u@h/db", "postgresql+psycopg://u@h/db"),
    ],
)
def test_database_url_gets_psycopg_driver(raw, expected):
    assert normalize_database_url(raw) == expected
    assert Settings.from_env({"DATABASE_URL": raw}).database_url == expected


def test_email_settings_default_to_resend_shared_sender():
    s = Settings.from_env({"RESEND_API_KEY": "re", "ADMIN_EMAIL": "me@example.com"})
    assert (s.resend_api_key, s.admin_email) == ("re", "me@example.com")
    assert s.email_from == "ptopilot <onboarding@resend.dev>"
    assert Settings.from_env({"EMAIL_FROM": "deals@example.com"}).email_from == "deals@example.com"
