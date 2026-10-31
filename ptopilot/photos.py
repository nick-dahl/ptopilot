"""Cover photos for places: Wikimedia Commons images, always shown with their attribution (spec §3.6).

Built-in places have hand-picked photos in geo.yaml. Other places get the Wikipedia lead image of their
city or region, looked up by the scan's `photos` stage (never inside a web request) and stored in
place_photos. Pages link to Wikimedia's thumbnail CDN rather than hosting the files.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from urllib.parse import quote, unquote

import httpx
import yaml
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from ptopilot.data import DATA_DIR, load_geo
from ptopilot.db.models import PlacePhotoRow

log = logging.getLogger(__name__)

USER_AGENT = "ptopilot/1.0 (https://github.com/nick-dahl/ptopilot)"  # Wikimedia's API policy asks for one
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UPLOAD = "https://upload.wikimedia.org/wikipedia/commons"
THUMB_WIDTH = 1280
MIN_WIDTH = 800  # narrower lead images look soft as a card cover
TIMEOUT_S = 10
# A Commons file, whether linked as the original or as one of its thumbnails.
COMMONS_FILE = re.compile(
    r"^https://(?:upload|thumb)\.wikimedia\.org/wikipedia/commons/(?:thumb/)?([0-9a-f])/([0-9a-f]{2})/([^/?#]+)"
)
COMMONS_FILE_PAGE = "https://commons.wikimedia.org/wiki/File:"
JPEG = re.compile(r"\.jpe?g$", re.IGNORECASE)
FREE_LICENCE = re.compile(r"^(CC0|CC BY(-SA)? \d|Public domain|PD\b)", re.IGNORECASE)


@dataclass(frozen=True)
class PlacePhoto:
    code: str  # "" until a place is known (a lookup by name)
    image_url: str
    width: int | None
    height: int | None
    author: str
    licence: str
    source_url: str  # the Commons file page

    @property
    def credit(self) -> str:
        return f"Photo: {self.author} · {self.licence}"


class PhotoUnavailable(Exception):
    """Wikipedia or Commons could not be reached (or answered with an error); try again another day."""


def http_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """A client for Wikimedia: named by our User-Agent, following redirects (renamed pages)."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S, follow_redirects=True, transport=transport
    )


def _get_json(client: httpx.Client, url: str, params: dict | None = None) -> dict | None:
    """The JSON answer; None for a 404 (no such page); PhotoUnavailable for an outage or other error."""
    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise PhotoUnavailable(f"{type(exc).__name__}: {exc}") from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise PhotoUnavailable(f"HTTP {response.status_code} from {url}")
    try:
        return response.json()
    except ValueError as exc:
        raise PhotoUnavailable(f"not JSON from {url}") from exc


def _lead_image(client: httpx.Client, title: str) -> dict | None:
    """The page's original lead image ({source, width, height}), or None (no page, no image, ambiguous)."""
    page = _get_json(client, SUMMARY_URL + quote(title.replace(" ", "_"), safe=""))
    if not page or page.get("type") == "disambiguation":
        return None
    image = page.get("originalimage")
    return image if isinstance(image, dict) and image.get("source") else None


def _plain(markup: str) -> str:
    """Commons' Artist field is HTML (links to user pages); the credit wants its text."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def _attribution(client: httpx.Client, file: str) -> tuple[str, str, str] | None:
    """(author, licence, file page) from the Commons file's metadata; None without a free licence."""
    found = _get_json(
        client,
        COMMONS_API,
        {
            "action": "query",
            "titles": f"File:{file}",
            "prop": "imageinfo",
            "iiprop": "extmetadata|url",
            "format": "json",
        },
    )
    pages = ((found or {}).get("query") or {}).get("pages") or {}
    info = next((p["imageinfo"][0] for p in pages.values() if p.get("imageinfo")), None)
    if info is None:
        return None
    meta = info.get("extmetadata") or {}
    licence = _plain((meta.get("LicenseShortName") or {}).get("value", ""))
    if not FREE_LICENCE.match(licence):
        return None
    author = _plain((meta.get("Artist") or {}).get("value", "")) or "Unknown author"
    page = info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/File:{quote(file)}"
    return author, licence, page


def _photo(client: httpx.Client, image: dict) -> PlacePhoto | None:
    match = COMMONS_FILE.match(image["source"])
    width, height = image.get("width") or 0, image.get("height") or 0
    if match is None:  # a local (non-free) Wikipedia upload, or some other host
        return None
    a, ab, encoded = match.groups()
    file = unquote(encoded)
    if not JPEG.search(file) or width < MIN_WIDTH:  # SVG maps and flags, PNG diagrams, small images
        return None
    found = _attribution(client, file)
    if found is None:
        return None
    name = quote(file, safe="")
    if width > THUMB_WIDTH:
        url = f"{UPLOAD}/thumb/{a}/{ab}/{name}/{THUMB_WIDTH}px-{name}"
        width, height = THUMB_WIDTH, round(height * THUMB_WIDTH / width) if height else None
    else:
        url = f"{UPLOAD}/{a}/{ab}/{name}"
    author, licence, page = found
    return PlacePhoto("", url, width, height or None, author, licence, page)


def fetch_photo(name: str, country_name: str, client: httpx.Client) -> PlacePhoto | None:
    """The lead image of `name`'s Wikipedia page, else of "name, country": None when neither has an
    acceptable one (a JPEG on Commons, at least MIN_WIDTH wide, under a free licence).

    Raises PhotoUnavailable when Wikimedia can't be reached, so an outage isn't stored as "no photo"."""
    titles = dict.fromkeys([name, f"{name}, {country_name}" if country_name else name])
    for title in titles:
        image = _lead_image(client, title)
        if image is not None and (photo := _photo(client, image)) is not None:
            return photo
    return None


def lookup_photo(name: str, country_name: str, client: httpx.Client) -> PlacePhoto | None:
    """fetch_photo, with an outage counted as no photo."""
    try:
        return fetch_photo(name, country_name, client)
    except PhotoUnavailable as exc:
        log.warning("photo lookup for %s failed: %s", name, exc)
        return None


@cache
def builtin_photos() -> dict[str, PlacePhoto]:
    """The hand-picked photos of the built-in places, from geo.yaml."""
    data = yaml.safe_load((DATA_DIR / "geo.yaml").read_text(encoding="utf-8"))
    return {
        code: PlacePhoto(
            code, p["image_url"], p.get("width"), p.get("height"), p["author"], p["licence"], p["source_url"]
        )
        for code, d in data["destinations"].items()
        if (p := d.get("photo"))
    }


def photo_block_problem(block: object) -> str | None:
    """Why a hand-picked photo block (geo.yaml, a gem) breaks the built-in photo rules, or None.

    The rules: the image is a Commons file, the author is named, the licence is free and source_url
    is the Commons file page."""
    if not isinstance(block, dict):
        return "photo must be a mapping"
    if not COMMONS_FILE.match(str(block.get("image_url") or "")):
        return "photo image_url must be a Wikimedia Commons file"
    if not str(block.get("author") or "").strip():
        return "photo needs an author"
    if not FREE_LICENCE.match(str(block.get("licence") or "")):
        return f"photo licence {block.get('licence')!r} is not a free licence"
    if not str(block.get("source_url") or "").startswith(COMMONS_FILE_PAGE):
        return "photo source_url must be its Commons file page"
    for key in ("width", "height"):
        if block.get(key) is not None and (not isinstance(block[key], int) or block[key] <= 0):
            return f"photo {key} must be a positive whole number"
    unknown = set(block) - {"image_url", "width", "height", "author", "licence", "source_url"}
    if unknown:
        return f"photo has unknown fields: {', '.join(sorted(unknown))}"
    return None


def _from_row(row: PlacePhotoRow) -> PlacePhoto:
    return PlacePhoto(
        row.code,
        row.image_url,
        row.width,
        row.height,
        row.author or "",
        row.licence or "",
        row.source_url or "",
    )


def photos_for(codes: Iterable[str], s: Session) -> dict[str, PlacePhoto]:
    """Each place's photo, by code: its geo.yaml photo, else a found one; places without one are left out."""
    wanted = set(codes)
    built = builtin_photos()
    out = {code: built[code] for code in wanted if code in built}
    rest = wanted - out.keys()
    if rest:
        rows = s.scalars(
            select(PlacePhotoRow).where(PlacePhotoRow.code.in_(rest), PlacePhotoRow.status == "ok")
        )
        out.update({row.code: _from_row(row) for row in rows if row.image_url})
    return out


def photo_for(code: str, s: Session) -> PlacePhoto | None:
    return photos_for([code], s).get(code)


def all_photos(s: Session) -> dict[str, PlacePhoto]:
    """Every photo the site can show, by code: the found ones, and the built-ins (which win)."""
    rows = s.scalars(select(PlacePhotoRow).where(PlacePhotoRow.status == "ok"))
    return {**{row.code: _from_row(row) for row in rows if row.image_url}, **builtin_photos()}


def photo_urls(engine: Engine, airport_sets: list[list[str]]) -> list[str | None]:
    """For place-search results: the photo of the place each airport set already is (built-in or added),
    matched like destinations.destination_code; None for a place nobody has added yet."""
    places = [
        d for d in (*load_geo().destinations(), *load_geo(engine).destinations()) if not d.return_airports
    ]
    codes = [  # built-ins first, as destination_code checks them
        next((d.code for d in places if frozenset(d.airports) == frozenset(airports)), None)
        for airports in airport_sets
    ]
    with Session(engine) as s:
        found = photos_for({c for c in codes if c}, s)
    return [found[c].image_url if c in found else None for c in codes]
