"""Hidden gems: hand-approved write-ups of affordable, off-the-beaten-path places (Plan 16, spec §3.2-3.3).

The catalogue is one YAML file per gem, named `{slug}.yaml`, written with the owner in working sessions
(see docs/gems/README.md and docs/gems/style-guide.md); nothing drafts gems in production.

Where the catalogue lives: `GEMS_DIR` (ptopilot/data/gems/, shipped with the package). Setting the
`PTOPILOT_GEMS_DIR` environment variable points the app and the pipeline at another folder (tests use
tests/fixtures/gems); `gems_dir()` resolves it, and `load_catalogue()` with no folder uses it.

    python -m ptopilot.gems check [--folder DIR] [--date YYYY-MM-DD]

validates every file and lists the claims older than GEM_CLAIM_STALE_DAYS; it exits 1 on invalid files.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path
from typing import Literal, get_args

import yaml
from markupsafe import Markup, escape

from ptopilot import config
from ptopilot.core.airports import AirportCatalog
from ptopilot.core.trip_styles import STYLES
from ptopilot.data import DATA_DIR
from ptopilot.photos import PlacePhoto, photo_block_problem

GEMS_DIR = DATA_DIR / "gems"
GEMS_DIR_ENV = "PTOPILOT_GEMS_DIR"

Status = Literal["draft", "approved", "retired"]
STATUSES: tuple[str, ...] = get_args(Status)
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HTTP_URL = re.compile(r"^https?://\S+$", re.IGNORECASE)

REQUIRED = (
    "slug",
    "name",
    "country",
    "airports",
    "styles",
    "best_months",
    "headline",
    "body",
    "budget",
    "daily_cost_usd",
    "status",
)
OPTIONAL = ("return_airports", "claims", "approved_on", "photo")


@dataclass(frozen=True)
class Claim:
    text: str
    source_url: str
    checked_on: date


@dataclass(frozen=True)
class Gem:
    slug: str
    name: str
    country: str  # ISO 3166 alpha-2 code
    airports: tuple[str, ...]
    return_airports: tuple[str, ...]
    styles: tuple[str, ...]
    best_months: tuple[int, ...]
    headline: str
    body: str  # the full guide, in render_markdown's subset
    budget: str
    daily_cost_usd: int
    claims: tuple[Claim, ...]
    status: Status
    approved_on: date | None
    photo: PlacePhoto | None

    @property
    def code(self) -> str:
        """The gem's place code, as photos and fares know it."""
        return f"gem-{self.slug}"

    @property
    def country_name(self) -> str:
        return AirportCatalog.load().country_name(self.country)


def gems_dir() -> Path:
    """The catalogue folder: PTOPILOT_GEMS_DIR when set, else the shipped one."""
    override = os.environ.get(GEMS_DIR_ENV)
    return Path(override) if override else GEMS_DIR


class _Invalid(ValueError):
    pass


def _text(data: dict, key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise _Invalid(f"{key} must be non-empty text")
    return value.strip()


def _list(data: dict, key: str) -> list:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise _Invalid(f"{key} must be a list")
    return value


def _date(value: object, key: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise _Invalid(f"{key} must be a date (YYYY-MM-DD), not {value!r}") from None


def _airports(data: dict, key: str, catalog: AirportCatalog) -> tuple[str, ...]:
    codes = []
    for code in _list(data, key):
        if not isinstance(code, str) or catalog.get(code) is None:
            raise _Invalid(f"{key}: {code!r} is not a catalogue airport")
        codes.append(code.strip().upper())
    return tuple(dict.fromkeys(codes))


def _claim(raw: object) -> Claim:
    if not isinstance(raw, dict) or set(raw) != {"text", "source_url", "checked_on"}:
        raise _Invalid("each claim needs exactly text, source_url and checked_on")
    url = raw["source_url"]
    if not isinstance(url, str) or not HTTP_URL.match(url):
        raise _Invalid(f"claim source_url {url!r} must be an http(s) URL")
    return Claim(_text(raw, "text"), url, _date(raw["checked_on"], "checked_on"))


def _parse(path: Path, catalog: AirportCatalog) -> Gem:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise _Invalid("the file must hold a mapping of fields")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise _Invalid(f"missing fields: {', '.join(missing)}")
    unknown = set(data) - set(REQUIRED) - set(OPTIONAL)
    if unknown:
        raise _Invalid(f"unknown fields: {', '.join(sorted(map(str, unknown)))}")

    slug = data["slug"]
    if not isinstance(slug, str) or not SLUG.match(slug):
        raise _Invalid(f"slug {slug!r} must be lowercase words joined by hyphens")
    if slug != path.stem:
        raise _Invalid(f"slug {slug!r} must match the file name ({path.stem})")

    country = data["country"]  # a bare NO is YAML for false: quote it ("NO")
    if not isinstance(country, str) or catalog.country_name(country) == country:
        raise _Invalid(f'country {country!r} must be a known ISO code (quote it, e.g. "NO")')

    airports = _airports(data, "airports", catalog)
    if not airports:
        raise _Invalid("airports must list at least one airport")
    return_airports = _airports(data, "return_airports", catalog)

    styles = _list(data, "styles")
    bad = [s for s in styles if s not in STYLES]
    if bad or not styles:
        raise _Invalid(f"styles must come from {', '.join(STYLES)}; got {bad or 'none'}")

    months = _list(data, "best_months")
    if not months or not all(isinstance(m, int) and not isinstance(m, bool) and 1 <= m <= 12 for m in months):
        raise _Invalid(f"best_months must be month numbers 1-12, got {months}")

    cost = data["daily_cost_usd"]
    if not isinstance(cost, int) or isinstance(cost, bool) or cost <= 0:
        raise _Invalid(f"daily_cost_usd must be a positive whole number, got {cost!r}")

    status = data["status"]
    if status not in STATUSES:
        raise _Invalid(f"status {status!r} must be one of {', '.join(STATUSES)}")
    claims = tuple(_claim(c) for c in _list(data, "claims"))
    approved_on = None if data.get("approved_on") is None else _date(data["approved_on"], "approved_on")
    if status == "approved" and approved_on is None:
        raise _Invalid("an approved gem needs approved_on")
    if status == "approved" and not claims:
        raise _Invalid("an approved gem needs at least one claim")

    photo = None
    if (block := data.get("photo")) is not None:
        if problem := photo_block_problem(block):
            raise _Invalid(f"{problem} (see Plan 15's built-in photo rules: a Commons file, free licence)")
        photo = PlacePhoto(
            f"gem-{slug}",
            block["image_url"],
            block.get("width"),
            block.get("height"),
            block["author"],
            block["licence"],
            block["source_url"],
        )

    return Gem(
        slug=slug,
        name=_text(data, "name"),
        country=country,
        airports=airports,
        return_airports=return_airports,
        styles=tuple(dict.fromkeys(styles)),
        best_months=tuple(sorted(set(months))),
        headline=_text(data, "headline"),
        body=_text(data, "body"),
        budget=_text(data, "budget"),
        daily_cost_usd=cost,
        claims=claims,
        status=status,
        approved_on=approved_on,
        photo=photo,
    )


def validate_folder(folder: Path) -> tuple[tuple[Gem, ...], list[str]]:
    """Every gem in the folder that parses, sorted, and an error per invalid file (naming the file)."""
    catalog = AirportCatalog.load()
    found: list[Gem] = []
    errors: list[str] = []
    for path in sorted(folder.glob("*.yaml")):
        try:
            found.append(_parse(path, catalog))
        except (_Invalid, yaml.YAMLError, KeyError) as exc:
            errors.append(f"{path.name}: {exc}")
    slugs = [g.slug for g in found]
    twice = sorted({s for s in slugs if slugs.count(s) > 1})
    errors += [f"{s}.yaml: slug {s!r} is used twice" for s in twice]
    found.sort(key=lambda g: (g.approved_on or date.max, g.slug))
    return tuple(found), errors


@cache
def _load(folder: Path) -> tuple[Gem, ...]:
    found, errors = validate_folder(folder)
    if errors:
        raise ValueError("invalid gems: " + "; ".join(errors))
    return found


def load_catalogue(folder: Path | None = None) -> tuple[Gem, ...]:
    """The gems in `folder` (default: gems_dir()), sorted by approved_on then slug, drafts last.

    Cached per folder. Raises ValueError naming the file on any invalid entry."""
    return _load(Path(folder or gems_dir()).resolve())


def approved(gems: Iterable[Gem]) -> tuple[Gem, ...]:
    return tuple(g for g in gems if g.status == "approved")


def stale_claims(gems: Iterable[Gem], today: date) -> list[tuple[Gem, Claim]]:
    """Claims last checked more than GEM_CLAIM_STALE_DAYS ago."""
    return [
        (g, c) for g in gems for c in g.claims if (today - c.checked_on).days > config.GEM_CLAIM_STALE_DAYS
    ]


# --- the Markdown subset -------------------------------------------------------------------------------
# Paragraphs, **bold**, *italic*, [text](https://...) links, "- " bullet lists and "## " subheadings.
# Everything else is escaped; links that aren't http(s) render as their text.

_LINK = re.compile(r"\[([^\[\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"\*([^*]+?)\*")


def _emphasis(text: str) -> str:
    """Bold and italic on already-escaped text."""
    return _ITALIC.sub(r"<em>\1</em>", _BOLD.sub(r"<strong>\1</strong>", text))


def _inline(text: str) -> str:
    out, last = [], 0
    for m in _LINK.finditer(text):
        out.append(_emphasis(str(escape(text[last : m.start()]))))
        label, url = _emphasis(str(escape(m.group(1)))), m.group(2)
        if HTTP_URL.match(url):
            out.append(f'<a href="{escape(url)}" rel="noopener">{label}</a>')
        else:
            out.append(label)
        last = m.end()
    out.append(_emphasis(str(escape(text[last:]))))
    return "".join(out)


def render_markdown(text: str) -> Markup:
    blocks: list[str] = []
    for chunk in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1 and lines[0].startswith("## "):
            blocks.append(f"<h2>{_inline(lines[0][3:].strip())}</h2>")
        elif all(line.startswith("- ") for line in lines):
            items = "".join(f"<li>{_inline(line[2:].strip())}</li>" for line in lines)
            blocks.append(f"<ul>{items}</ul>")
        else:
            blocks.append(f"<p>{_inline(' '.join(lines))}</p>")
    return Markup("\n".join(blocks))


# --- python -m ptopilot.gems check ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ptopilot.gems")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate the catalogue and list stale claims")
    check.add_argument("--folder", type=Path, default=None, help="default: the shipped folder")
    check.add_argument("--date", type=date.fromisoformat, default=None, help="as of (default: today)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # a Windows console can't print every place name
        sys.stdout.reconfigure(errors="replace")

    folder = args.folder or gems_dir()
    today = args.date or datetime.now(UTC).date()
    found, errors = validate_folder(folder)
    counts = ", ".join(f"{sum(g.status == s for g in found)} {s}" for s in STATUSES)
    if errors:
        print(f"{len(errors)} invalid file(s) in {folder}:")
        for error in errors:
            print(f"  {error}")
    else:
        print(f"{len(found)} gems OK ({counts}) in {folder}")
    stale = stale_claims([g for g in found if g.status != "retired"], today)
    if stale:
        print(f"{len(stale)} stale claim(s), last checked over {config.GEM_CLAIM_STALE_DAYS} days ago:")
        for gem, claim in stale:
            print(f"  {gem.slug} ({gem.status}): {claim.text}")
            print(f"    checked {claim.checked_on}: {claim.source_url}")
    else:
        print("No stale claims.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
