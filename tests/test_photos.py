"""Cover photos: Wikipedia lead images from Wikimedia Commons, with attribution (fake transport)."""

import re
from urllib.parse import unquote

import httpx
import yaml

from ptopilot.data import DATA_DIR
from ptopilot.photos import USER_AGENT, PlacePhoto, builtin_photos, http_client, lookup_photo

COMMONS = "https://upload.wikimedia.org/wikipedia/commons"
FREE = re.compile(r"^(CC0|CC BY(-SA)? \d|Public domain|PD\b)")


def summary(source: str, width: int = 4000, height: int = 3000, kind: str = "standard") -> dict:
    return {"type": kind, "originalimage": {"source": source, "width": width, "height": height}}


JANE = '<a href="//commons.wikimedia.org/wiki/User:Jane">Jane&nbsp;Doe</a>'  # Commons' Artist is HTML


def metadata(artist=JANE, licence="CC BY-SA 4.0"):
    return {"Artist": {"value": artist}, "LicenseShortName": {"value": licence}}


def fake(pages: dict, files: dict | None = None, seen: list | None = None) -> httpx.Client:
    """Wikipedia summaries by title (a dict, a status code or an exception) and Commons metadata by file."""
    files = files or {}

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == USER_AGENT
        if seen is not None:
            seen.append(request.url)
        if request.url.host == "en.wikipedia.org":
            title = unquote(request.url.path.rsplit("/", 1)[-1]).replace("_", " ")
            page = pages.get(title, 404)
        else:
            name = request.url.params["titles"].removeprefix("File:")
            meta = files.get(name)
            page = (
                {"query": {"pages": {"-1": {"missing": ""}}}}
                if meta is None
                else {
                    "query": {
                        "pages": {
                            "7": {
                                "imageinfo": [
                                    {
                                        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}",
                                        "extmetadata": meta,
                                    }
                                ]
                            }
                        }
                    }
                }
            )
        if isinstance(page, Exception):
            raise page
        if isinstance(page, int):
            return httpx.Response(page, json={"type": "not_found"})
        return httpx.Response(200, json=page)

    return http_client(transport=httpx.MockTransport(handle))


def test_a_jpeg_lead_image_is_accepted_with_attribution():
    client = fake(
        {"Funchal": summary(f"{COMMONS}/a/ab/Funchal_bay.jpg?utm_source=en.wikipedia.org", 4000, 3000)},
        {"Funchal_bay.jpg": metadata()},
    )
    assert lookup_photo("Funchal", "Portugal", client) == PlacePhoto(
        code="",
        image_url=f"{COMMONS}/thumb/a/ab/Funchal_bay.jpg/1280px-Funchal_bay.jpg",
        width=1280,
        height=960,
        author="Jane Doe",
        licence="CC BY-SA 4.0",
        source_url="https://commons.wikimedia.org/wiki/File:Funchal_bay.jpg",
    )


def test_a_lead_image_given_as_a_thumbnail_maps_back_to_its_file():
    thumb = (
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/08/Pico_%2C_2025.jpg/3840px-Pico_%2C_2025.jpg"
    )
    client = fake({"Pico": summary(thumb, 4032, 2268)}, {"Pico_,_2025.jpg": metadata("Krib", "CC0")})
    photo = lookup_photo("Pico", "Portugal", client)
    assert photo.image_url == f"{COMMONS}/thumb/0/08/Pico_%2C_2025.jpg/1280px-Pico_%2C_2025.jpg"
    assert (photo.author, photo.licence, photo.height) == ("Krib", "CC0", 720)


def test_a_lead_image_narrower_than_the_thumbnail_is_used_as_is():
    client = fake({"Horta": summary(f"{COMMONS}/c/cd/Horta.JPG", 1000, 600)}, {"Horta.JPG": metadata()})
    photo = lookup_photo("Horta", "Portugal", client)
    assert (photo.image_url, photo.width, photo.height) == (f"{COMMONS}/c/cd/Horta.JPG", 1000, 600)


def test_maps_flags_small_and_missing_images_are_rejected():
    flag = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a4/Flag.svg/1280px-Flag.svg.png"
    cases = {
        "Flagland": summary(flag, 1200, 800),  # an SVG map or flag
        "Smallville": summary(f"{COMMONS}/1/12/Small.jpg", 640, 480),  # under 800 px wide
        "Pngtown": summary(f"{COMMONS}/2/23/Map.png", 2000, 1500),  # not a JPEG
        "Localfile": summary("https://upload.wikimedia.org/wikipedia/en/3/34/Poster.jpg"),  # not on Commons
        "Noimage": {"type": "standard"},
        "Slowtown": httpx.ReadTimeout("timed out"),
    }
    files = {"Small.jpg": metadata(), "Map.png": metadata(), "Poster.jpg": metadata()}
    client = fake(cases, files)
    for name in [*cases, "Nowhere"]:  # Nowhere: 404 for every title
        assert lookup_photo(name, "Utopia", client) is None, name


def test_unfree_or_unattributed_files_are_rejected():
    client = fake(
        {"Gfdl": summary(f"{COMMONS}/4/45/G.jpg"), "Gone": summary(f"{COMMONS}/5/56/Gone.jpg")},
        {"G.jpg": metadata(licence="GFDL")},  # Gone.jpg: no Commons file page
    )
    assert lookup_photo("Gfdl", "Utopia", client) is None
    assert lookup_photo("Gone", "Utopia", client) is None


def test_name_then_name_and_country_are_tried():
    seen: list = []
    client = fake(
        {
            "Santa Cruz": summary(f"{COMMONS}/6/67/Any.jpg", kind="disambiguation"),
            "Santa Cruz, Bolivia": summary(f"{COMMONS}/7/78/Santa_Cruz.jpg"),
        },
        {"Santa_Cruz.jpg": metadata("Ana")},
        seen,
    )
    photo = lookup_photo("Santa Cruz", "Bolivia", client)
    assert photo is not None and photo.author == "Ana"
    titles = [unquote(u.path.rsplit("/", 1)[-1]) for u in seen if u.host == "en.wikipedia.org"]
    assert titles == ["Santa_Cruz", "Santa_Cruz,_Bolivia"]


def test_the_client_names_itself_to_wikimedia():
    assert http_client().headers["user-agent"] == "ptopilot/1.0 (https://github.com/nick-dahl/ptopilot)"


def test_built_in_photos_have_free_licences_and_commons_sources():
    geo = yaml.safe_load((DATA_DIR / "geo.yaml").read_text(encoding="utf-8"))
    blocks = {code: d.get("photo") for code, d in geo["destinations"].items()}
    assert set(blocks) == {"TH", "LIS", "TYO", "PATAGONIA", "AZORES", "MADEIRA", "CAMINO_PORTUGUES"}
    for code, block in blocks.items():
        assert block, f"{code} has no photo"
        assert block["image_url"].startswith(f"{COMMONS}/thumb/"), code
        assert "/1280px-" in block["image_url"], code
        assert block["author"].strip(), code
        assert FREE.match(block["licence"]), f"{code}: {block['licence']}"
        assert block["source_url"].startswith("https://commons.wikimedia.org/wiki/File:"), code
    built = builtin_photos()
    assert set(built) == set(blocks) and built["AZORES"].code == "AZORES"
