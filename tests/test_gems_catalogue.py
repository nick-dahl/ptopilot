"""The hidden-gems catalogue: its YAML format, loader, Markdown subset and check command (Plan 16)."""

from __future__ import annotations

import shutil
import tomllib
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from ptopilot import config, gems
from ptopilot.gems import Claim, approved, load_catalogue, render_markdown, stale_claims

FIXTURES = Path(__file__).parent / "fixtures" / "gems"


def _valid() -> dict:
    return yaml.safe_load((FIXTURES / "hoegvik-islands.yaml").read_text(encoding="utf-8"))


def _write(folder: Path, slug: str, data: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_fixture_catalogue_loads_and_sorts():
    found = load_catalogue(FIXTURES)
    assert [g.slug for g in found] == ["lipnica-valley", "hoegvik-islands", "ardmore-falls"]
    hoegvik = found[1]
    assert hoegvik.code == "gem-hoegvik-islands"
    assert hoegvik.airports == ("BOO",) and hoegvik.return_airports == ("SVJ",)
    assert hoegvik.styles == ("hiking_camping", "islands")
    assert hoegvik.best_months == (6, 7, 8)
    assert hoegvik.status == "approved" and hoegvik.approved_on == date(2026, 6, 1)
    assert hoegvik.daily_cost_usd == 45
    assert hoegvik.claims[0] == Claim(
        hoegvik.claims[0].text, "https://example.org/hoegvik/camping", date(2026, 5, 20)
    )
    assert hoegvik.photo is not None and hoegvik.photo.code == "gem-hoegvik-islands"
    assert hoegvik.photo.licence == "CC BY-SA 4.0"
    assert hoegvik.country_name == "Norway"
    assert load_catalogue(FIXTURES) is found  # cached


@pytest.mark.parametrize(
    "change, message",
    [
        ({"styles": ["hiking_camping", "spelunking"]}, "spelunking"),
        ({"airports": ["BOO", "QQQ"]}, "QQQ"),
        ({"return_airports": ["ZZZ"]}, "ZZZ"),
        ({"claims": []}, "claim"),
        ({"approved_on": None}, "approved_on"),
        ({"best_months": [0, 7]}, "month"),
        ({"slug": "somewhere-else"}, "slug"),
        ({"status": "published"}, "status"),
        ({"country": "XX"}, "country"),
        ({"daily_cost_usd": "cheap"}, "daily_cost_usd"),
        ({"surprise": 1}, "surprise"),
        ({"claims": [{"text": "x", "source_url": "ftp://example.org", "checked_on": "2026-01-01"}]}, "http"),
        ({"photo": {**_valid()["photo"], "licence": "All rights reserved"}}, "licence"),
        ({"photo": {**_valid()["photo"], "source_url": "https://example.org/photo"}}, "Commons"),
        ({"photo": {**_valid()["photo"], "image_url": "https://example.org/a.jpg"}}, "Commons"),
    ],
)
def test_invalid_entries_name_their_file(tmp_path, change, message):
    data = {**_valid(), **change}
    path = _write(tmp_path, "hoegvik-islands", data)
    with pytest.raises(ValueError) as raised:
        load_catalogue(tmp_path)
    assert path.name in str(raised.value)
    assert message in str(raised.value)


def test_a_missing_field_names_its_file(tmp_path):
    data = _valid()
    del data["headline"]
    _write(tmp_path, "hoegvik-islands", data)
    with pytest.raises(ValueError, match=r"hoegvik-islands\.yaml.*headline"):
        load_catalogue(tmp_path)


def test_a_draft_needs_no_claims_or_approval_date(tmp_path):
    data = {**_valid(), "status": "draft", "approved_on": None, "claims": [], "photo": None}
    _write(tmp_path, "hoegvik-islands", data)
    (gem,) = load_catalogue(tmp_path)
    assert gem.status == "draft" and gem.claims == () and gem.photo is None


def test_only_approved_gems_are_approved(tmp_path):
    shutil.copytree(FIXTURES, tmp_path, dirs_exist_ok=True)
    retired = {**_valid(), "slug": "old-coast", "status": "retired"}
    _write(tmp_path, "old-coast", retired)
    found = load_catalogue(tmp_path)
    assert {g.status for g in found} == {"approved", "draft", "retired"}
    assert [g.slug for g in approved(found)] == ["lipnica-valley", "hoegvik-islands"]


def test_stale_claims_are_listed():
    found = load_catalogue(FIXTURES)
    hoegvik = next(g for g in found if g.slug == "hoegvik-islands")
    checked = hoegvik.claims[0].checked_on
    assert stale_claims([hoegvik], checked + timedelta(days=config.GEM_CLAIM_STALE_DAYS)) == []
    stale = stale_claims([hoegvik], checked + timedelta(days=400))
    assert (hoegvik, hoegvik.claims[0]) in stale


def test_markdown_escapes_html_and_unsafe_links():
    out = str(render_markdown('<script>alert("x")</script> and [x](javascript:alert(1)) & more'))
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "href" not in out and "javascript:" not in out
    assert "x" in out and "&amp; more" in out
    out = str(render_markdown('[evil](https://example.org/"onmouseover="alert(1))'))
    assert '"onmouseover' not in out and "&#34;onmouseover=&#34;" in out


def test_markdown_renders_the_subset():
    text = (
        "## Getting there\n\n"
        "Fly into **Bodø**, then take the *ferry*.\nIt runs daily.\n\n"
        "- Camp for free\n- Bring a stove\n\n"
        "See [the operator](https://example.org/ferry?a=1&b=2)."
    )
    out = str(render_markdown(text))
    assert out == (
        "<h2>Getting there</h2>\n"
        "<p>Fly into <strong>Bodø</strong>, then take the <em>ferry</em>. It runs daily.</p>\n"
        "<ul><li>Camp for free</li><li>Bring a stove</li></ul>\n"
        '<p>See <a href="https://example.org/ferry?a=1&amp;b=2" rel="noopener">the operator</a>.</p>'
    )


def test_shipped_catalogue_is_valid():
    found = load_catalogue()
    assert all(g.status in ("draft", "approved", "retired") for g in found)


def test_the_folder_can_be_pointed_elsewhere(monkeypatch):
    monkeypatch.setenv("PTOPILOT_GEMS_DIR", str(FIXTURES))
    assert gems.gems_dir() == FIXTURES
    assert [g.slug for g in load_catalogue()][0] == "lipnica-valley"
    monkeypatch.delenv("PTOPILOT_GEMS_DIR")
    assert gems.gems_dir() == gems.GEMS_DIR


def test_check_command_exit_codes(tmp_path, capsys):
    assert gems.main(["check", "--folder", str(FIXTURES), "--date", "2026-10-31"]) == 0
    out = capsys.readouterr().out
    assert "3 gems OK" in out and "No stale claims" in out

    assert gems.main(["check", "--folder", str(FIXTURES), "--date", "2028-01-01"]) == 0
    out = capsys.readouterr().out
    assert "hoegvik-islands" in out and "stale" in out.lower()

    shutil.copytree(FIXTURES, tmp_path, dirs_exist_ok=True)
    _write(tmp_path, "broken", {**_valid(), "slug": "broken", "styles": ["spelunking"]})
    assert gems.main(["check", "--folder", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "broken.yaml" in out and "spelunking" in out


def test_the_package_ships_the_catalogue():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert "gems/*.yaml" in pyproject["tool"]["setuptools"]["package-data"]["ptopilot.data"]
    assert gems.GEMS_DIR.is_dir()
