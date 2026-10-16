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
