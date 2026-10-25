"""Build ptopilot/data/airports.csv and countries.csv from OurAirports (public domain).

Usage: python scripts/build_airport_data.py [SOURCE_DIR]
With SOURCE_DIR, reads airports.csv and countries.csv from that directory instead of downloading.
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
from pathlib import Path

BASE_URL = "https://davidmegginson.github.io/ourairports-data/"
OUT_DIR = Path(__file__).resolve().parent.parent / "ptopilot" / "data"
SIZES = {"large_airport": "large", "medium_airport": "medium", "small_airport": "small"}


def _read(name: str, source: Path | None) -> list[dict[str, str]]:
    if source is not None:
        text = (source / name).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(BASE_URL + name, timeout=60) as resp:  # noqa: S310
            text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def build(source: Path | None = None) -> tuple[int, int]:
    airports = {}
    for row in _read("airports.csv", source):
        code = row["iata_code"].strip().upper()
        size = SIZES.get(row["type"])
        if row["scheduled_service"] != "yes" or not code or size is None:
            continue
        airports[code] = {
            "code": code,
            "name": row["name"],
            "city": row["municipality"],
            "country": row["iso_country"],
            "continent": row["continent"],
            "lat": f"{float(row['latitude_deg']):.4f}",
            "lon": f"{float(row['longitude_deg']):.4f}",
            "size": size,
        }
    countries = sorted(
        (
            {"code": r["code"], "name": r["name"], "continent": r["continent"]}
            for r in _read("countries.csv", source)
        ),
        key=lambda r: r["code"],
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write(
        OUT_DIR / "airports.csv",
        ["code", "name", "city", "country", "continent", "lat", "lon", "size"],
        [airports[c] for c in sorted(airports)],
    )
    _write(OUT_DIR / "countries.csv", ["code", "name", "continent"], countries)
    return len(airports), len(countries)


def _write(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    n_air, n_cty = build(src)
    print(f"wrote {n_air} airports and {n_cty} countries to {OUT_DIR}")
